# INF8175 - Projet Quoridor - Automne 2026 - Equipe 50
# Anders Antoine   - 2252046
# Adam Lecavalier  - 2253227

from __future__ import annotations

import random
import time
from collections import deque

from actions_quoridor import Orientation, Wall
from game_state_quoridor import GameStateQuoridor
from player_quoridor import PlayerQuoridor
from seahorse.game.action import Action
from seahorse.game.stateless_action import StatelessAction


class _TimeUp(Exception):
    """Raised to unwind the search as soon as the per-move time budget is exhausted."""


# ----------------------------------------------------------------------
# Evaluation. Scores are integers in hundredths of a pawn step, so the
# principal-variation search can use an exact null window (alpha, alpha + 1).
# ----------------------------------------------------------------------
W_DISTANCE = 100           # one step of shortest-path lead
W_WALLS = 124              # one wall in hand, worth 1.24 steps: logistic fit of 6159 positions on
                           # game outcome, and the average net gain of a wall in 30 real games
WALL_FADE = 1              # a wall in hand only has its full value while the opponent is at least
                           # this many steps from its goal; nearer than that it fades linearly,
                           # since there are fewer turns left to place it. 1 means no fading.
# W_WALLS and WALL_FADE are the two parameters tools/local_search.py tunes by hill climbing.
# That search (10 matches of 80 games) ended where it started: no neighbour of (124, 1) held up,
# the one accepted at 57.5% (W_WALLS=134) scoring 49.4% over 160 confirmation games, and fading
# scored 51% and 46%. So both values stay, now as a measured local optimum rather than a guess.
TEMPO = 50                 # half a step for the side to move. Leaves do not all sit at the same
                           # depth once late moves are reduced, and without this term a line cut
                           # one ply shorter would look a whole step better or worse than it is.
WIN_SCORE = 10_000_000
INFINITY = 1_000_000_000

# ----------------------------------------------------------------------
# Search.
# ----------------------------------------------------------------------
MAX_DEPTH = 40
MAX_WALL_CANDIDATES = 28   # wall slots considered per node, counted before the path-existence test
MAX_TT_ENTRIES = 1_000_000   # about 200 MB at ~200 bytes an entry, far below the 4 GB limit
GAIN_ORDER_MIN_DEPTH = 3   # from this remaining depth up, walls are ordered by their measured effect
                           # on both shortest paths. Costs about one path search per wall, which only
                           # pays where the subtree below is large (about 1 node in 80).
LMR_MIN_DEPTH = 3          # late-move reduction: at this remaining depth or more...
LMR_FULL_MOVES = 4         # ...every move after the first few is first tried one ply shallower,
                           # and searched at full depth only if that already beats alpha.
HISTORY_MAX = 1 << 20
CLOCK_CHECK_INTERVAL = 256  # nodes between two looks at the clock (a node costs ~0.05 ms)

EXACT, LOWER, UPPER = 0, 1, 2

# ----------------------------------------------------------------------
# Time management (seconds).
# ----------------------------------------------------------------------
SAFETY_MARGIN = 3.0        # always left unspent, to absorb IPC/serialization latency
MIN_BUDGET = 0.05
MAX_MOVE_BUDGET = 20.0     # no single move may claim more than this, whatever the estimate says
MAX_BUDGET_FRACTION = 0.2  # nor more than this share of the time left, so the tail can never run dry
MIN_MOVES_LEFT = 12        # floor on the remaining-move estimate, for the same reason
QUIET_OPENING_PLIES = 4    # with no wall on the board yet, the first steps are forced advancing
QUIET_OPENING_BUDGET = 1.0
RACE_BUDGET = 0.5          # neither side has a wall left: the game is a pure race, nothing to search
NEXT_DEPTH_FRACTION = 0.45 # do not start a deeper pass once this share of the budget is spent: it
                           # costs about 4x the previous one and would be thrown away unfinished

# ----------------------------------------------------------------------
# Repetition (root only, see MyPlayer._repetition_cost).
# ----------------------------------------------------------------------
HISTORY_LENGTH = 6         # how many of my own recent squares to remember
W_REPETITION = 32          # penalty for stepping back onto a recent square. Small against
                           # W_DISTANCE, so a genuinely necessary detour around a wall still wins,
                           # but an A-B-A oscillation does not.
STALL_PLIES = 150          # past this, escalate the penalty until repetition is impossible.
STALL_GROWTH = 20.0        # plies per doubling of the penalty once escalation starts.
                           # Why: when a player is losing every line, minimax prefers the loss
                           # that is furthest away, so shuffling forever outscores advancing.
                           # A real match did exactly that for 2992 plies and was cancelled.

NORTH, SOUTH, WEST, EAST = 0, 1, 2, 3
# Same order as GameStateQuoridor.DIRECTIONS, so move generation matches the engine's.
_DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))
_OPPOSITE = (SOUTH, NORTH, EAST, WEST)
_OPPOSITE_AXIS = ((WEST, EAST), (WEST, EAST), (NORTH, SOUTH), (NORTH, SOUTH))


# ======================================================================
# Move encoding
# ======================================================================
# Inside the search a move is one int, so it can index tables directly:
#     pawn move        -> destination cell                (0 .. size-1)
#     horizontal wall  -> size   + row * dim + col
#     vertical wall    -> 2*size + row * dim + col
# where cell = row * dim + col and size = dim * dim.


def _wall_values(length: int = 512) -> list[int]:
    """
    Value of one wall in hand, indexed by the distance the OTHER player still
    has to walk: a wall is only worth something while there is time to use it.
    Built from the module constants when an agent is created.
    """
    return [W_WALLS * min(distance, WALL_FADE) // WALL_FADE for distance in range(length)]


class _Geometry:
    """
    Board tables that depend only on the dimension, computed once and shared.

    The search runs on plain ints and bitmasks instead of the engine's Wall
    objects and frozensets: rebuilding those at every node is what limited
    the first versions to depth 2-3.
    """

    _cache: dict[int, "_Geometry"] = {}

    def __init__(self, dim: int) -> None:
        self.dim = dim
        size = self.size = dim * dim

        self.row_of = [cell // dim for cell in range(size)]
        self.neighbours = [[-1] * 4 for _ in range(size)]
        # direction[(a, b)] is the direction of the step from cell a to adjacent cell b.
        self.direction: dict[tuple[int, int], int] = {}
        for row in range(dim):
            for col in range(dim):
                cell = row * dim + col
                for direction, (d_row, d_col) in enumerate(_DELTAS):
                    n_row, n_col = row + d_row, col + d_col
                    if 0 <= n_row < dim and 0 <= n_col < dim:
                        neighbour = n_row * dim + n_col
                        self.neighbours[cell][direction] = neighbour
                        self.direction[(cell, neighbour)] = direction

        # Per wall code. A crossing is the pair (cell, direction); it is
        # identified by the int cell * 4 + direction where a set is needed.
        self.wall_valid = bytearray(3 * size)                    # slot lies inside the board
        self.wall_edges: list[tuple] = [()] * (3 * size)         # ((cell, direction bit), ...)
        self.wall_cuts: list[frozenset] = [frozenset()] * (3 * size)   # crossing ids it closes
        self.wall_conflicts: list[tuple] = [()] * (3 * size)     # slots it overlaps or crosses
        for row in range(dim):
            for col in range(dim):
                h_code, v_code = size + row * dim + col, 2 * size + row * dim + col
                # Bounds as the engine checks them (GameStateQuoridor._is_wall_legal).
                self.wall_valid[h_code] = col < dim - 1
                self.wall_valid[v_code] = row < dim - 1
                for code, edges in ((h_code, self._horizontal_edges(row, col)),
                                    (v_code, self._vertical_edges(row, col))):
                    self.wall_edges[code] = tuple((cell, 1 << d) for cell, d in edges)
                    self.wall_cuts[code] = frozenset(cell * 4 + d for cell, d in edges)
                self.wall_conflicts[h_code] = tuple(
                    code for code in (h_code, self.h_code(row, col + 1), self.h_code(row, col - 1),
                                      self.v_code(row - 1, col + 1)) if code >= 0)
                self.wall_conflicts[v_code] = tuple(
                    code for code in (v_code, self.v_code(row - 1, col), self.v_code(row + 1, col),
                                      self.h_code(row + 1, col - 1)) if code >= 0)

        # Inverse table: which walls could close a given crossing.
        # Mirrors GameStateQuoridor._candidate_blocking_walls, bounds included.
        self.blockers: list[list[tuple]] = [[() for _ in range(4)] for _ in range(size)]
        for row in range(dim):
            for col in range(dim):
                cell = row * dim + col
                south, north, east, west = [], [], [], []
                if col > 0:
                    south.append(self.h_code(row + 1, col - 1))
                    north.append(self.h_code(row, col - 1))
                if col < dim - 1:
                    south.append(self.h_code(row + 1, col))
                    north.append(self.h_code(row, col))
                if row > 0:
                    east.append(self.v_code(row - 1, col + 1))
                    west.append(self.v_code(row - 1, col))
                if row < dim - 1:
                    east.append(self.v_code(row, col + 1))
                    west.append(self.v_code(row, col))
                for direction, codes in ((SOUTH, south), (NORTH, north), (EAST, east), (WEST, west)):
                    self.blockers[cell][direction] = tuple(c for c in codes if c >= 0)

        # Left-right mirror. The board is symmetric about the middle column and
        # both goals are rows, so a position and its mirror have equal value.
        # Verified against the engine: horizontal walls map c -> dim-2-c and
        # vertical walls c -> dim-c (dim-1-c for vertical walls is wrong).
        self.mirror_cell = [row * dim + (dim - 1 - col) for row in range(dim) for col in range(dim)]
        # mirror_move[code]: the same move seen in the mirrored frame, or -1
        # for the few edge slots whose mirror image falls outside the encoding
        # (they close no crossing, so the search never generates them).
        self.mirror_move = [-1] * (3 * size)
        for row in range(dim):
            for col in range(dim):
                cell = row * dim + col
                self.mirror_move[cell] = self.mirror_cell[cell]
                self.mirror_move[size + cell] = self.h_code(row, dim - 2 - col)
                self.mirror_move[2 * size + cell] = self.v_code(row, dim - col)

    def h_code(self, row: int, col: int) -> int:
        """Code of the horizontal wall at (row, col), or -1 outside the grid."""
        dim = self.dim
        return self.size + row * dim + col if 0 <= row < dim and 0 <= col < dim else -1

    def v_code(self, row: int, col: int) -> int:
        """Code of the vertical wall at (row, col), or -1 outside the grid."""
        dim = self.dim
        return 2 * self.size + row * dim + col if 0 <= row < dim and 0 <= col < dim else -1

    def _horizontal_edges(self, row: int, col: int) -> list[tuple[int, int]]:
        """A horizontal wall at (row, col) closes the two north-south crossings beneath it."""
        dim = self.dim
        edges = []
        if 1 <= row < dim:
            for c in (col, col + 1):
                if 0 <= c < dim:
                    edges.append(((row - 1) * dim + c, SOUTH))
                    edges.append((row * dim + c, NORTH))
        return edges

    def _vertical_edges(self, row: int, col: int) -> list[tuple[int, int]]:
        """A vertical wall at (row, col) closes the two east-west crossings beside it."""
        dim = self.dim
        edges = []
        if 1 <= col < dim:
            for r in (row, row + 1):
                if 0 <= r < dim:
                    edges.append((r * dim + col - 1, EAST))
                    edges.append((r * dim + col, WEST))
        return edges

    @classmethod
    def get(cls, dim: int) -> "_Geometry":
        geometry = cls._cache.get(dim)
        if geometry is None:
            geometry = cls(dim)
            cls._cache[dim] = geometry
        return geometry


class _Zobrist:
    """Incremental hash keys, so a node's key costs a few XORs instead of hashing every wall."""

    _cache: dict[int, "_Zobrist"] = {}

    def __init__(self, dim: int) -> None:
        rng = random.Random(0x5EED)
        size = dim * dim
        bits = 64
        h_keys = [[rng.getrandbits(bits) for _ in range(dim)] for _ in range(dim)]
        # dim+1 columns: a vertical wall at column 0 mirrors to column dim.
        v_keys = [[rng.getrandbits(bits) for _ in range(dim + 1)] for _ in range(dim)]
        self.pawn = [[rng.getrandbits(bits) for _ in range(size)] for _ in range(2)]
        self.walls_left = [[rng.getrandbits(bits) for _ in range(32)] for _ in range(2)]
        self.side = rng.getrandbits(bits)

        # Per wall code: its own key, and the key of its mirror image.
        self.wall = [0] * (3 * size)
        self.wall_mirror = [0] * (3 * size)
        for row in range(dim):
            for col in range(dim):
                h_code, v_code = size + row * dim + col, 2 * size + row * dim + col
                self.wall[h_code] = h_keys[row][col]
                self.wall[v_code] = v_keys[row][col]
                # Slots whose mirror falls off the grid close no crossing; any
                # fixed key keeps the hash consistent for them.
                self.wall_mirror[h_code] = h_keys[row][(dim - 2 - col) % dim]
                self.wall_mirror[v_code] = v_keys[row][dim - col]

    @classmethod
    def get(cls, dim: int) -> "_Zobrist":
        table = cls._cache.get(dim)
        if table is None:
            table = cls(dim)
            cls._cache[dim] = table
        return table


class _Board:
    """
    Mutable board the search works on, with make/unmake instead of copying.

    Players are indexed 0/1 internally (0 is always the side we play);
    `player_ids` maps back to engine ids.
    """

    __slots__ = ("geo", "zobrist", "dim", "size", "blocked", "occupied", "pawns", "goals",
                 "walls_left", "player_ids", "turn", "hash", "hash_mirror")

    def __init__(self, state: GameStateQuoridor, my_id: int) -> None:
        dim = state.rep.dimension
        self.geo = _Geometry.get(dim)
        self.zobrist = _Zobrist.get(dim)
        self.dim = dim
        self.size = dim * dim
        self.blocked = [0] * self.size            # per cell: bitmask of closed directions
        self.occupied = bytearray(3 * self.size)  # per wall code: is that wall on the board

        opponent_id = next(p.id for p in state.players if p.id != my_id)
        self.player_ids = (my_id, opponent_id)

        players = {p.id: p for p in state.players}
        self.pawns = []
        self.goals = []
        self.walls_left = []
        for pid in self.player_ids:
            row, col = state.rep.pawn_positions[pid]
            self.pawns.append(row * dim + col)
            self.goals.append(players[pid].get_goal_row())
            self.walls_left.append(state.rep.remaining_walls.get(pid, 0))

        for wall in state.rep.walls:
            if wall.orientation == Orientation.HORIZONTAL:
                code = self.geo.h_code(wall.row, wall.col)
            else:
                code = self.geo.v_code(wall.row, wall.col)
            if code >= 0:
                self.place(code)

        self.turn = 0 if state.active_player.id == my_id else 1
        self.hash, self.hash_mirror = self._full_hashes()

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def _full_hashes(self) -> tuple[int, int]:
        """Hash of this position, and of its left-right mirror, from scratch."""
        z, geo = self.zobrist, self.geo
        value = mirrored = 0
        for code in range(self.size, 3 * self.size):
            if self.occupied[code]:
                value ^= z.wall[code]
                mirrored ^= z.wall_mirror[code]
        for player in (0, 1):
            value ^= z.pawn[player][self.pawns[player]]
            mirrored ^= z.pawn[player][geo.mirror_cell[self.pawns[player]]]
            left = z.walls_left[player][self.walls_left[player]]
            value ^= left
            mirrored ^= left
        if self.turn:
            value ^= z.side
            mirrored ^= z.side
        return value, mirrored

    # ------------------------------------------------------------------
    # Wall bookkeeping
    # ------------------------------------------------------------------

    def place(self, code: int) -> None:
        """Put a wall on the board without touching turn, counters or hashes."""
        blocked = self.blocked
        for cell, bit in self.geo.wall_edges[code]:
            blocked[cell] |= bit
        self.occupied[code] = 1

    def remove(self, code: int) -> None:
        blocked = self.blocked
        for cell, bit in self.geo.wall_edges[code]:
            blocked[cell] &= ~bit
        self.occupied[code] = 0

    def wall_fits(self, code: int) -> bool:
        """Inside the board and neither overlapping nor crossing a wall already placed."""
        if not self.geo.wall_valid[code]:
            return False
        occupied = self.occupied
        for other in self.geo.wall_conflicts[code]:
            if occupied[other]:
                return False
        return True

    def wall_legal(self, code: int, placer: int | None = None) -> bool:
        """Full legality, mirroring GameStateQuoridor._is_wall_legal exactly."""
        if self.walls_left[self.turn if placer is None else placer] <= 0:
            return False
        if not self.wall_fits(code):
            return False
        self.place(code)
        ok = self.has_path(0) and self.has_path(1)
        self.remove(code)
        return ok

    # ------------------------------------------------------------------
    # Make / unmake
    # ------------------------------------------------------------------

    def make_move(self, cell: int) -> int:
        player = self.turn
        previous = self.pawns[player]
        z = self.zobrist
        self.pawns[player] = cell
        mirror = self.geo.mirror_cell
        self.hash ^= z.pawn[player][previous] ^ z.pawn[player][cell] ^ z.side
        self.hash_mirror ^= (z.pawn[player][mirror[previous]]
                             ^ z.pawn[player][mirror[cell]] ^ z.side)
        self.turn ^= 1
        return previous

    def unmake_move(self, previous: int) -> None:
        self.turn ^= 1
        player = self.turn
        cell = self.pawns[player]
        z = self.zobrist
        self.pawns[player] = previous
        mirror = self.geo.mirror_cell
        self.hash ^= z.pawn[player][cell] ^ z.pawn[player][previous] ^ z.side
        self.hash_mirror ^= (z.pawn[player][mirror[cell]]
                             ^ z.pawn[player][mirror[previous]] ^ z.side)

    def make_wall(self, code: int) -> None:
        player = self.turn
        self.place(code)
        left = self.walls_left[player]
        self.walls_left[player] = left - 1
        z = self.zobrist
        shared = z.walls_left[player][left] ^ z.walls_left[player][left - 1] ^ z.side
        self.hash ^= z.wall[code] ^ shared
        self.hash_mirror ^= z.wall_mirror[code] ^ shared
        self.turn ^= 1

    def unmake_wall(self, code: int) -> None:
        self.turn ^= 1
        player = self.turn
        self.remove(code)
        left = self.walls_left[player]
        self.walls_left[player] = left + 1
        z = self.zobrist
        shared = z.walls_left[player][left] ^ z.walls_left[player][left + 1] ^ z.side
        self.hash ^= z.wall[code] ^ shared
        self.hash_mirror ^= z.wall_mirror[code] ^ shared

    # ------------------------------------------------------------------
    # Pawn moves (mirrors GameStateQuoridor._try_direction, jumps included)
    # ------------------------------------------------------------------

    def pawn_destinations(self, player: int) -> list[int]:
        destinations: list[int] = []
        other = self.pawns[1 - player]
        for direction in range(4):
            self._try_direction(self.pawns[player], direction, other, destinations)
        unique = []
        for cell in destinations:
            if cell not in unique:
                unique.append(cell)
        return unique

    def _try_direction(self, cell: int, direction: int, other: int, out: list[int]) -> None:
        nxt = self.geo.neighbours[cell][direction]
        if nxt < 0 or self.blocked[cell] & (1 << direction):
            return
        if nxt == other:
            beyond = self.geo.neighbours[nxt][direction]
            if beyond >= 0 and not self.blocked[nxt] & (1 << direction):
                self._try_direction(nxt, direction, other, out)
            else:
                for side in _OPPOSITE_AXIS[direction]:
                    self._try_direction(nxt, side, other, out)
            return
        out.append(nxt)

    # ------------------------------------------------------------------
    # Path finding (ignores pawns, like the engine's _shortest_path)
    # ------------------------------------------------------------------

    def distance(self, player: int) -> int | None:
        """Shortest distance to the goal row, or None if walled in. A* with
        the admissible 'rows remaining' heuristic and a bucket queue."""
        start = self.pawns[player]
        goal_row = self.goals[player]
        row_of = self.geo.row_of
        if row_of[start] == goal_row:
            return 0

        neighbours = self.geo.neighbours
        blocked = self.blocked
        size = self.size

        best = [-1] * size
        best[start] = 0
        # f = cost + rows-to-goal; a winding path can cost up to size-1, so the
        # queue must reach size-1 + (dim-1), not just a couple of board widths.
        buckets: list[list[int]] = [[] for _ in range(size + self.dim)]
        buckets[abs(row_of[start] - goal_row)].append(start)

        for f in range(len(buckets)):
            bucket = buckets[f]
            index = 0
            while index < len(bucket):
                cell = bucket[index]
                index += 1
                cost = best[cell]
                if cost + abs(row_of[cell] - goal_row) != f:
                    continue  # stale entry, a cheaper path to this cell was found
                if row_of[cell] == goal_row:
                    return cost
                mask = blocked[cell]
                row = neighbours[cell]
                for direction in range(4):
                    if mask & (1 << direction):
                        continue
                    nxt = row[direction]
                    if nxt < 0:
                        continue
                    new_cost = cost + 1
                    if best[nxt] == -1 or new_cost < best[nxt]:
                        best[nxt] = new_cost
                        buckets[new_cost + abs(row_of[nxt] - goal_row)].append(nxt)
        return None

    def has_path(self, player: int) -> bool:
        """Reachability only, depth-first with early exit: cheaper than a full distance."""
        start = self.pawns[player]
        goal_row = self.goals[player]
        row_of = self.geo.row_of
        if row_of[start] == goal_row:
            return True

        neighbours = self.geo.neighbours
        blocked = self.blocked
        seen = bytearray(self.size)
        seen[start] = 1
        stack = [start]
        while stack:
            cell = stack.pop()
            mask = blocked[cell]
            row = neighbours[cell]
            for direction in range(4):
                if mask & (1 << direction):
                    continue
                nxt = row[direction]
                if nxt < 0 or seen[nxt]:
                    continue
                if row_of[nxt] == goal_row:
                    return True
                seen[nxt] = 1
                stack.append(nxt)
        return False

    def shortest_path(self, player: int) -> list[int]:
        """Cells of one shortest path, pawn square first; empty if walled in."""
        start = self.pawns[player]
        goal_row = self.goals[player]
        row_of = self.geo.row_of
        neighbours = self.geo.neighbours
        blocked = self.blocked

        parent = [-2] * self.size
        parent[start] = -1
        queue = [start]
        index = 0
        while index < len(queue):
            cell = queue[index]
            index += 1
            if row_of[cell] == goal_row:
                path = []
                while cell != -1:
                    path.append(cell)
                    cell = parent[cell]
                path.reverse()
                return path
            mask = blocked[cell]
            row = neighbours[cell]
            for direction in range(4):
                if mask & (1 << direction):
                    continue
                nxt = row[direction]
                if nxt >= 0 and parent[nxt] == -2:
                    parent[nxt] = cell
                    queue.append(nxt)
        return []

    def crossings(self, path: list[int]) -> set[int]:
        """
        Ids of the crossings a path uses, in both directions.

        A wall can only lengthen (or cut) a player's route if it closes one of
        these: if it closes none, the same path is still there afterwards, so
        that player's distance is unchanged and needs no new search.
        """
        direction = self.geo.direction
        used = set()
        for cell, nxt in zip(path, path[1:]):
            d = direction[(cell, nxt)]
            used.add(cell * 4 + d)
            used.add(nxt * 4 + _OPPOSITE[d])
        return used


class MyPlayer(PlayerQuoridor):
    """
    Quoridor agent: iterative-deepening principal-variation search (alpha-beta
    with null windows) on a fast mutable board.

    What separates this version from the previous one is depth. Thirty real
    games showed that walls have increasing returns: a first wall costs the
    opponent about one step, the sixth to tenth about three each, because
    each one builds on the barrier already standing. Such a plan only pays
    off on its third to fifth wall, i.e. 6 to 10 plies ahead, and a 4-5 ply
    search can neither find it nor see the opponent's coming. So:

      * a node is about ten times cheaper: distances are inherited from the
        parent unless a wall actually closes a crossing of the known shortest
        path, and wall legality is only established for moves really searched;
      * the transposition table is keyed by position alone, so the best move
        of one deepening pass orders the next;
      * killer moves, a history table and (near the root) the measured effect
        of each wall order the moves, and late moves are searched one ply
        shallower first (late-move reductions);
      * the time saved in forced openings and pure races is spent where the
        wall war is decided.

    Attributes:
        piece_type (str): piece type of the player
    """

    # Test switches (class attributes, so they never reach the game JSON).
    # With _strict set, a table entry is only reused at exactly the depth it
    # was stored for and mirror positions are kept apart, so the search must
    # return the plain minimax value: that is what tools/test_search.py checks.
    _strict = False
    _reductions = True

    def __init__(self, piece_type: str, goal_row: int = 0, name: str = "bob", *args, **kwargs) -> None:
        """
        Initialize the PlayerQuoridor instance.

        Args:
            piece_type (str): Type of the player's game piece
            goal_row (int): The row the player wants to reach
            name (str, optional): Name of the player (default is "bob")
        """
        super().__init__(piece_type, goal_row, name, *args, **kwargs)
        # All underscore-prefixed, so none of this reaches the public game JSON.
        self._tt = {}            # transposition table: key -> (depth, value, flag, best move)
        self._history = []       # per move code: how often it caused a cut-off
        self._killers = []       # per ply: the two latest moves that caused a cut-off there
        self._recent = deque(maxlen=HISTORY_LENGTH)  # my own recent pawn squares
        self._last_step = None   # to detect a new game on a reused instance
        self._deadline = 0.0
        self._nodes = 0
        self._next_clock_check = 0
        self._partial = None     # best root move proven so far in an unfinished pass
        self._reached_depth = 0  # last fully completed depth (for tools and tests)
        self._wall_value = _wall_values()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def compute_action(self, current_state: GameStateQuoridor, remaining_time: float = 15 * 60, **kwargs) -> Action:
        """
        Choose the best action found by iterative deepening within the time
        budget allocated for this move.

        Args:
            current_state (GameStateQuoridor): The current game state.
            remaining_time (float): Time left, in seconds, for the rest of the whole game.

        Returns:
            Action: The selected legal action.
        """
        # The clock starts here, not after the setup below: everything this
        # method does counts against the move's budget.
        start = time.perf_counter()

        self._record_position(current_state)
        board = _Board(current_state, current_state.active_player.id)
        budget = self._time_budget(board, remaining_time, current_state.get_step())

        moves = self._root_moves(board)
        if not moves:
            return self._engine_fallback(current_state)
        if len(moves) == 1:
            return self._to_engine_action(board, moves[0], current_state)

        best_move = self._search(board, moves, start, budget)
        return self._to_engine_action(board, best_move, current_state)

    def _search(self, board: _Board, moves: list[int], start: float, budget: float,
                max_depth: int = MAX_DEPTH) -> int:
        """Iterative deepening over `moves`; returns the best move found in time."""
        self._deadline = start + budget
        self._nodes = 0
        self._next_clock_check = 0
        self._reached_depth = 0
        self._killers = [[-1, -1] for _ in range(MAX_DEPTH + 2)]
        if len(self._history) != 3 * board.size:
            self._history = [0] * (3 * board.size)
        else:
            # Age rather than reset: last move's refutations are still a good guess.
            self._history = [h >> 2 for h in self._history]

        # Cheap guaranteed fallback. Depth 1 refines it almost immediately,
        # so it only has to be legal and sane, not good.
        best_move = self._fallback_move(board, moves)
        moves = [best_move] + [m for m in moves if m != best_move]

        try:
            for depth in range(1, max_depth + 1):
                best_move, value = self._search_root(board, moves, depth)
                self._reached_depth = depth
                # The proven best move goes first in the next, deeper pass.
                moves = [best_move] + [m for m in moves if m != best_move]
                if abs(value) >= WIN_SCORE:
                    break  # forced win or loss: more depth cannot change the verdict
                if time.perf_counter() - start > budget * NEXT_DEPTH_FRACTION:
                    break
        except _TimeUp:
            # An unfinished pass is still worth something: it searched the
            # previous best move first, so any move that has beaten it since
            # was proven better at the greater depth.
            if self._partial is not None:
                best_move = self._partial
        return best_move

    def _time_budget(self, board: _Board, remaining_time: float, step: int = 0) -> float:
        """
        Share of the whole-game budget granted to this move.

        Estimated from my own remaining turns (at best one row per turn, plus
        the turns spent placing walls). Three caps keep a single move from
        ever claiming an absurd slice: an absolute ceiling, a fraction of what
        is left, and a floor under the remaining-move estimate.

        Two situations get almost nothing because there is nothing to decide:
        the first steps on an empty board, and a pure race once all walls are
        gone. Everything in between is the wall war, which real games showed
        opponents open as early as ply 4 to 12; the previous version capped
        its first 16 plies at 2.5 s and so met that phase half asleep, while
        finishing its games with 450 s or more unspent.
        """
        if remaining_time <= SAFETY_MARGIN:
            return 0.0
        usable = remaining_time - SAFETY_MARGIN

        if board.walls_left[0] == 0 and board.walls_left[1] == 0:
            ceiling = RACE_BUDGET
        elif step < QUIET_OPENING_PLIES and not any(board.occupied):
            ceiling = QUIET_OPENING_BUDGET
        else:
            ceiling = MAX_MOVE_BUDGET

        my_distance = board.distance(board.turn) or 0
        moves_left_estimate = max(MIN_MOVES_LEFT, my_distance + board.walls_left[board.turn])
        budget = min(usable / moves_left_estimate, ceiling, usable * MAX_BUDGET_FRACTION)
        return max(min(MIN_BUDGET, usable), budget)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search_root(self, board: _Board, moves: list[int], depth: int) -> tuple[int, int]:
        """
        One deepening pass over the root moves (all legal, best guess first).
        Returns the chosen move and its search value, or raises `_TimeUp`;
        `self._partial` then holds the best move proven in the unfinished pass.

        The repetition penalty exists only here. Each move is asked the exact
        question that matters, "is your value minus your penalty better than
        the best so far?", with a null window placed at that threshold, so
        the penalty decides between root moves without ever entering the tree.
        """
        self._partial = None
        path_me = board.shortest_path(0)
        path_op = board.shortest_path(1)
        info = (len(path_me) - 1, len(path_op) - 1, path_me,
                board.crossings(path_me), board.crossings(path_op))

        best_move = moves[0]
        best_adjusted = -INFINITY
        best_value = -INFINITY
        for index, move in enumerate(moves):
            cost = self._repetition_cost(board, move)
            if index == 0:
                value = self._search_child(board, move, depth, -INFINITY, INFINITY, info, 0)
            else:
                threshold = best_adjusted + cost
                value = self._search_child(board, move, depth, threshold, threshold + 1, info, 0)
                if value is not None and value > threshold:
                    value = self._search_child(board, move, depth, threshold, INFINITY, info, 0)
            if value is None:
                continue
            if value - cost > best_adjusted:
                best_adjusted = value - cost
                best_value = value
                best_move = move
            # Valid from the first move on: that one was the previous pass's
            # choice, now searched one ply deeper.
            self._partial = best_move
        return best_move, best_value

    def _search_child(self, board: _Board, move: int, depth: int, alpha: int, beta: int,
                      info: tuple, ply: int) -> int | None:
        """
        Play `move`, search the resulting position to `depth - 1` with the
        window (alpha, beta) seen from the mover, and take the move back.
        Returns the value for the mover, or None if the move is an illegal
        wall (one that leaves a pawn with no route).

        `info` describes the position before the move: both distances, the
        mover's shortest path, and the crossings used by each shortest path.
        """
        d_me, d_op, path_me, cross_me, cross_op = info
        mover = board.turn

        if move < board.size:
            previous = board.make_move(move)
            if depth == 1:
                # The child is a leaf and needs both distances. Only the
                # mover's can have changed, and following the known shortest
                # path shortens it by exactly one.
                if len(path_me) > 1 and move == path_me[1]:
                    d_me -= 1
                else:
                    d_me = board.distance(mover)
            value = -self._negamax(board, depth - 1, -beta, -alpha, d_op, d_me, ply + 1)
            board.unmake_move(previous)
            return value

        cuts = board.geo.wall_cuts[move]
        cuts_op = not cuts.isdisjoint(cross_op)
        cuts_me = not cuts.isdisjoint(cross_me)
        board.make_wall(move)
        # A wall that closes no crossing of a shortest path leaves that path
        # standing: distance unchanged, and certainly still a route. Only the
        # players it does touch need a new search, which also settles legality.
        if depth == 1:
            if cuts_op:
                d_op = board.distance(1 - mover)
            if cuts_me and d_op is not None:
                d_me = board.distance(mover)
            legal = d_op is not None and d_me is not None
        else:
            legal = ((not cuts_op or board.has_path(1 - mover))
                     and (not cuts_me or board.has_path(mover)))
        value = None
        if legal:
            value = -self._negamax(board, depth - 1, -beta, -alpha, d_op, d_me, ply + 1)
        board.unmake_wall(move)
        return value

    def _negamax(self, board: _Board, depth: int, alpha: int, beta: int,
                 d_me: int, d_op: int, ply: int) -> int:
        """
        Value of the position for the side to move, searched `depth` plies
        deep inside the window (alpha, beta). `d_me` and `d_op` are the
        shortest distances of the side to move and of its opponent; they are
        only read at depth 0, where the caller always knows them.
        """
        self._nodes += 1
        if self._nodes >= self._next_clock_check:
            self._next_clock_check = self._nodes + CLOCK_CHECK_INTERVAL
            if time.perf_counter() >= self._deadline:
                raise _TimeUp()

        turn = board.turn
        other = 1 - turn
        geo = board.geo
        # Only the player who has just moved can be standing on its goal row.
        if geo.row_of[board.pawns[other]] == board.goals[other]:
            return -(WIN_SCORE + depth)
        if depth <= 0:
            wall_value = self._wall_value
            return (W_DISTANCE * (d_op - d_me) + wall_value[d_op] * board.walls_left[turn]
                    - wall_value[d_me] * board.walls_left[other] + TEMPO)

        # ---- transposition table -------------------------------------
        strict = self._strict
        mirrored = not strict and board.hash_mirror < board.hash
        key = board.hash_mirror if mirrored else board.hash
        entry = self._tt.get(key)
        tt_move = -1
        if entry is not None:
            e_depth, e_value, e_flag, tt_move = entry
            if mirrored and tt_move >= 0:
                tt_move = geo.mirror_move[tt_move]
            if e_depth == depth or (e_depth > depth and not strict):
                if e_flag == EXACT:
                    return e_value
                if e_flag == LOWER:
                    if e_value >= beta:
                        return e_value
                elif e_value <= alpha:
                    return e_value

        # ---- this position -------------------------------------------
        path_me = board.shortest_path(turn)
        path_op = board.shortest_path(other)
        d_me, d_op = len(path_me) - 1, len(path_op) - 1
        cross_me, cross_op = board.crossings(path_me), board.crossings(path_op)
        info = (d_me, d_op, path_me, cross_me, cross_op)

        ordered = self._ordered_moves(board, depth, ply, tt_move, info, path_op)

        alpha_start = alpha
        best_value = -INFINITY
        best_move = -1
        searched = 0
        size = board.size

        if depth == 1:
            # ---- frontier: every child is a leaf ----------------------
            # Four nodes in five are such leaves, so they are scored right
            # here, without playing the move on the board: a pawn move only
            # changes the mover's distance, a wall only the distance of a
            # player whose shortest path it closes.
            wall_value = self._wall_value
            walls_me, walls_op = board.walls_left[turn], board.walls_left[other]
            forward = path_me[1] if d_me > 0 else -1
            goal_row = board.goals[turn]
            row_of = geo.row_of
            wall_cuts = geo.wall_cuts
            pawns = board.pawns
            here = pawns[turn]
            for move in ordered:
                if move < size:
                    if row_of[move] == goal_row:
                        value = WIN_SCORE
                    else:
                        if move == forward:
                            after_me = d_me - 1
                        else:
                            pawns[turn] = move
                            after_me = board.distance(turn)
                            pawns[turn] = here
                        value = (W_DISTANCE * (d_op - after_me) + wall_value[d_op] * walls_me
                                 - wall_value[after_me] * walls_op - TEMPO)
                else:
                    cuts = wall_cuts[move]
                    after_op, after_me = d_op, d_me
                    cuts_op = not cuts.isdisjoint(cross_op)
                    cuts_me = not cuts.isdisjoint(cross_me)
                    if cuts_op or cuts_me:
                        board.place(move)
                        if cuts_op:
                            after_op = board.distance(other)
                        if cuts_me and after_op is not None:
                            after_me = board.distance(turn)
                        board.remove(move)
                        if after_op is None or after_me is None:
                            continue  # illegal: it would wall a pawn in
                    value = (W_DISTANCE * (after_op - after_me)
                             + wall_value[after_op] * (walls_me - 1)
                             - wall_value[after_me] * walls_op - TEMPO)
                self._nodes += 1
                searched += 1
                if value > best_value:
                    best_value = value
                    best_move = move
                    if value > alpha:
                        alpha = value
                        if alpha >= beta:
                            self._record_cutoff(move, depth, ply)
                            break
        else:
            # ---- principal-variation search ---------------------------
            reduce_from = LMR_FULL_MOVES if (self._reductions and depth >= LMR_MIN_DEPTH) else 1 << 30
            for move in ordered:
                if searched == 0:
                    value = self._search_child(board, move, depth, alpha, beta, info, ply)
                else:
                    # Everything after the first move is expected to fail low,
                    # so ask only "do you beat alpha?"; late walls are even
                    # asked one ply shallower first. A yes is always
                    # re-searched properly.
                    reduced = searched >= reduce_from and move >= size
                    value = self._search_child(board, move, depth - 1 if reduced else depth,
                                               alpha, alpha + 1, info, ply)
                    if value is not None and value > alpha and reduced:
                        value = self._search_child(board, move, depth, alpha, alpha + 1, info, ply)
                    if value is not None and alpha < value < beta:
                        value = self._search_child(board, move, depth, alpha, beta, info, ply)
                if value is None:
                    continue  # illegal wall
                searched += 1
                if value > best_value:
                    best_value = value
                    best_move = move
                    if value > alpha:
                        alpha = value
                        if alpha >= beta:
                            self._record_cutoff(move, depth, ply)
                            break

        if searched == 0:
            # No legal action at all (a pawn boxed in by the other pawn):
            # score the position as it stands.
            wall_value = self._wall_value
            return (W_DISTANCE * (d_op - d_me) + wall_value[d_op] * board.walls_left[turn]
                    - wall_value[d_me] * board.walls_left[other] + TEMPO)

        # A value at or below the original alpha is only an upper bound, one
        # at or above beta only a lower bound; anything in between is exact.
        if best_value <= alpha_start:
            flag = UPPER
        elif best_value >= beta:
            flag = LOWER
        else:
            flag = EXACT
        if len(self._tt) >= MAX_TT_ENTRIES:
            self._tt.clear()
        self._tt[key] = (depth, best_value, flag,
                         geo.mirror_move[best_move] if mirrored else best_move)
        return best_value

    def _record_cutoff(self, move: int, depth: int, ply: int) -> None:
        """Remember a move that refuted its parent: it is likely to do so again nearby."""
        killers = self._killers[ply]
        if killers[0] != move:
            killers[1] = killers[0]
            killers[0] = move
        history = self._history
        history[move] += depth * depth
        if history[move] > HISTORY_MAX:
            for index in range(len(history)):
                history[index] >>= 1

    # ------------------------------------------------------------------
    # Move generation and ordering
    # ------------------------------------------------------------------

    def _wall_candidates(self, board: _Board, path_me: list[int], path_op: list[int]) -> list[int]:
        """
        Wall slots worth considering: those that close a crossing of the
        opponent's shortest path or of our own, and fit on the board. A wall
        touching neither path changes neither distance this ply.

        Whether each leaves both pawns a route is NOT checked here: that
        costs a path search, and most candidates of a node are never reached
        because an earlier move already produced a cut-off.
        """
        if board.walls_left[board.turn] <= 0:
            return []
        blockers = board.geo.blockers
        direction = board.geo.direction
        seen = set()
        walls = []
        for path in (path_op, path_me):
            for cell, nxt in zip(path, path[1:]):
                for code in blockers[cell][direction[(cell, nxt)]]:
                    if code not in seen:
                        seen.add(code)
                        if board.wall_fits(code):
                            walls.append(code)
                            if len(walls) >= MAX_WALL_CANDIDATES:
                                return walls
        return walls

    def _ordered_moves(self, board: _Board, depth: int, ply: int, tt_move: int,
                       info: tuple, path_op: list[int]) -> list[int]:
        """
        Every move to try at this node, most promising first: alpha-beta only
        prunes well if the best move comes early.

        Order: the transposition-table move, the step along our shortest
        path, then walls (killer moves first, then by history or, near the
        root, by their measured effect on both paths), then the other pawn
        moves.
        """
        d_me, d_op, path_me, cross_me, cross_op = info
        turn = board.turn
        pawn_moves = board.pawn_destinations(turn)
        walls = self._wall_candidates(board, path_me, path_op)

        history = self._history
        killers = self._killers[ply]
        if depth >= GAIN_ORDER_MIN_DEPTH and walls:
            # Measure what each wall does to both distances. Expensive, so
            # only where the subtree below is large; illegal walls drop out
            # here as a side effect.
            wall_cuts = board.geo.wall_cuts
            scored = []
            for code in walls:
                cuts = wall_cuts[code]
                after_op, after_me = d_op, d_me
                board.place(code)
                if not cuts.isdisjoint(cross_op):
                    after_op = board.distance(1 - turn)
                if after_op is not None and not cuts.isdisjoint(cross_me):
                    after_me = board.distance(turn)
                board.remove(code)
                if after_op is None or after_me is None:
                    continue  # would wall a pawn in
                gain = (after_op - d_op) - (after_me - d_me)
                bonus = 2 if code == killers[0] else 1 if code == killers[1] else 0
                scored.append((gain * 4 + bonus, history[code], code))
            scored.sort(reverse=True)
            walls = [code for _, _, code in scored]
        elif walls:
            walls.sort(key=lambda code: (code == killers[0] or code == killers[1], history[code]),
                       reverse=True)

        forward = path_me[1] if len(path_me) > 1 else -1
        ordered = []
        if tt_move >= 0 and (tt_move in pawn_moves or tt_move in walls):
            ordered.append(tt_move)
        if forward in pawn_moves and forward != tt_move:
            ordered.append(forward)
        ordered.extend(code for code in walls if code != tt_move)
        ordered.extend(cell for cell in pawn_moves if cell != tt_move and cell != forward)
        return ordered

    def _root_moves(self, board: _Board) -> list[int]:
        """Every legal move considered at the root: pawn moves, then legal wall candidates."""
        path_me = board.shortest_path(0)
        path_op = board.shortest_path(1)
        walls = [code for code in self._wall_candidates(board, path_me, path_op)
                 if board.wall_legal(code)]
        return board.pawn_destinations(0) + walls

    # ------------------------------------------------------------------
    # Repetition
    # ------------------------------------------------------------------

    def _record_position(self, state: GameStateQuoridor) -> None:
        """
        Remember where my pawn has just been, so the root can refuse to walk
        back onto it. Clears when the step counter goes backwards, which means
        a new game started on a reused player instance.
        """
        step = state.get_step()
        if self._last_step is not None and step < self._last_step:
            self._recent.clear()
            self._tt.clear()
        self._last_step = step

        position = state.rep.pawn_positions[self.id]
        if not self._recent or self._recent[-1] != position:
            self._recent.append(position)

    def _repetition_cost(self, board: _Board, move: int) -> int:
        """Cost of returning to a recently occupied square; the more recent, the worse."""
        if move >= board.size or not self._recent:
            return 0
        destination = (move // board.dim, move % board.dim)
        # _recent[-1] is the square I am standing on, which no move can target,
        # so age starts at 1: the square I just came from carries the full cost.
        for age, position in enumerate(reversed(self._recent)):
            if age and position == destination:
                overtime = max(0, (self._last_step or 0) - STALL_PLIES)
                return int((W_REPETITION / age) * (1.0 + overtime / STALL_GROWTH))
        return 0

    def _fallback_move(self, board: _Board, moves: list[int]) -> int:
        """
        The pawn move that gets closest to the goal, or any legal move if
        none advances. Only a handful of path computations, so it still
        completes when the budget is nearly zero.
        """
        best_move = moves[0]
        best_distance = INFINITY
        for move in moves:
            if move >= board.size:
                continue
            previous = board.make_move(move)
            distance = board.distance(0)
            board.unmake_move(previous)
            if distance is not None and distance < best_distance:
                best_distance = distance
                best_move = move
        return best_move

    # ------------------------------------------------------------------
    # Conversion back to engine actions
    # ------------------------------------------------------------------

    def _to_engine_action(self, board: _Board, move: int, state: GameStateQuoridor) -> Action:
        """
        Build the engine action, and verify it against the engine's own rules.

        The search runs on a reimplementation of the game rules, so a single
        divergence would mean an illegal action and an instant loss. This
        check costs one legality call per turn, against the ~270ms it would
        take to enumerate every legal action.
        """
        dim, size = board.dim, board.size
        if move < size:
            destination = (move // dim, move % dim)
            if any(a.data["destination"] == destination for a in state._legal_moves()):
                return StatelessAction({"type": "move", "destination": destination})
        else:
            is_horizontal = move < 2 * size
            row, col = divmod(move % size, dim)
            orientation = Orientation.HORIZONTAL if is_horizontal else Orientation.VERTICAL
            if state._is_wall_legal(Wall(row, col, orientation)):
                return StatelessAction({
                    "type": "horizontal" if is_horizontal else "vertical",
                    "destination": (row, col),
                })
        return self._engine_fallback(state)

    @staticmethod
    def _engine_fallback(state: GameStateQuoridor) -> Action:
        """Last resort: ask the engine itself, so we can never return an illegal action."""
        for action in state.generate_possible_stateless_actions():
            return action
        raise RuntimeError("No legal action available.")
