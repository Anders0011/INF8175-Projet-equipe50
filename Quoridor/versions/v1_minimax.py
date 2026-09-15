from __future__ import annotations

import time
from collections import deque
from math import inf

from actions_quoridor import Orientation
from game_state_quoridor import GameStateQuoridor
from player_quoridor import PlayerQuoridor
from seahorse.game.action import Action
from seahorse.game.stateless_action import StatelessAction
from seahorse.player.player import Player


class _TimeUp(Exception):
    """Raised to unwind the search as soon as the per-move time budget is exhausted."""


# Heuristic weights, tuned empirically against greedy_player_quoridor.py / random_player_quoridor.py.
W_DISTANCE = 25.0
W_WALLS = 2.0
W_MOBILITY = 0.2

WIN_SCORE = 1_000_000.0
NO_PATH_SCORE = 500_000.0

SAFETY_MARGIN = 1.0        # seconds always left unspent, to absorb IPC/serialization latency
MIN_BUDGET = 0.05
MAX_WALL_CANDIDATES = 24   # branching-factor cap for wall moves considered at any search node
MAX_TT_ENTRIES = 200_000
MAX_DEPTH = 30


class MyPlayer(PlayerQuoridor):
    """
    Quoridor agent driven by iterative-deepening alpha-beta minimax.

    The whole-game time budget (15 minutes total, enforced by seahorse's
    GameMaster) is split across moves in `_time_budget`, and the search is
    aborted cleanly via `_TimeUp` as soon as that per-move budget runs out,
    falling back to the best move found at the last fully completed depth.

    Attributes:
        piece_type (str): piece type of the player
    """

    def __init__(self, piece_type: str, goal_row: int = 0, name: str = "bob", *args, **kwargs) -> None:
        """
        Initialize the PlayerQuoridor instance.

        Args:
            piece_type (str): Type of the player's game piece
            goal_row (int): The row the player wants to reach
            name (str, optional): Name of the player (default is "bob")
        """
        super().__init__(piece_type, goal_row, name, *args, **kwargs)
        self._tt = {}  # transposition table; prefixed with `_` so it stays out of the JSON export

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def compute_action(self, current_state: GameStateQuoridor, remaining_time: float = 15 * 60, **kwargs) -> Action:
        """
        Choose the best action found by iterative-deepening alpha-beta search
        within the time budget allocated for this move.

        Args:
            current_state (GameStateQuoridor): The current game state.
            remaining_time (float): Time left, in seconds, for the rest of the whole game.

        Returns:
            Action: The selected legal action.
        """
        legal_actions = tuple(current_state.generate_possible_stateless_actions())
        if not legal_actions:
            raise RuntimeError("No legal action available.")
        if len(legal_actions) == 1:
            return legal_actions[0]

        me = current_state.active_player
        opponent = self._opponent(current_state, me)

        # Guaranteed fallback: a fast depth-1 choice, in case the deeper search never completes.
        best_action = self._best_shallow_action(current_state, legal_actions, me.id, opponent.id)

        deadline = time.perf_counter() + self._time_budget(current_state, me, opponent, remaining_time)

        depth = 1
        try:
            while depth <= MAX_DEPTH:
                action, _ = self._search_root(current_state, legal_actions, depth, me.id, opponent.id, deadline)
                if action is not None:
                    best_action = action
                depth += 1
        except _TimeUp:
            pass

        return best_action

    def _time_budget(self, state: GameStateQuoridor, me: Player, opponent: Player, remaining_time: float) -> float:
        """
        Splits the whole-game time budget across moves: fewer moves are
        expected to remain as pawns get closer to their goal and walls run
        out, so later moves get a bigger share automatically.
        """
        if remaining_time <= SAFETY_MARGIN:
            return 0.0

        my_distance = state._shortest_path(me) or 0
        opponent_distance = state._shortest_path(opponent) or 0
        walls_left = state.rep.remaining_walls.get(me.id, 0) + state.rep.remaining_walls.get(opponent.id, 0)
        moves_left_estimate = max(4, my_distance + opponent_distance + walls_left // 2)

        usable = remaining_time - SAFETY_MARGIN
        budget = usable / moves_left_estimate
        return max(MIN_BUDGET, min(budget, usable * 0.5))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search_root(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...],
        depth: int,
        my_id: int,
        opponent_id: int,
        deadline: float,
    ) -> tuple[Action | None, float]:
        """
        One full iterative-deepening pass: explores every candidate action at
        the root and returns the best one found, or raises `_TimeUp` if the
        budget runs out before every root action has been explored (the
        partial result is then discarded by the caller).
        """
        actions = self._candidate_actions(state, legal_actions=legal_actions)
        tt_key = (hash(state.rep), state.active_player.id, depth)
        cached = self._tt.get(tt_key)
        tt_move_key = cached[2] if cached else None
        actions = self._order_actions(state, actions, tt_move_key)

        alpha, beta = -inf, inf
        best_action = None
        best_value = -inf

        for action in actions:
            child = state.apply_action(action)
            value = self._alphabeta(child, depth - 1, alpha, beta, False, my_id, opponent_id, deadline)

            if value > best_value:
                best_value = value
                best_action = action
            alpha = max(alpha, value)

        # Root search always uses the full (-inf, inf) window, so a completed
        # pass never fails high/low: the value is always exact here.
        if best_action is not None:
            self._store_tt(tt_key, best_value, "EXACT", self._action_key(best_action))

        return best_action, best_value

    def _alphabeta(
        self,
        state: GameStateQuoridor,
        depth: int,
        alpha: float,
        beta: float,
        maximizing: bool,
        my_id: int,
        opponent_id: int,
        deadline: float,
    ) -> float:
        """
        Standard alpha-beta minimax, bounded by `deadline` (checked at every
        node) and using a depth-keyed transposition table to reuse work
        across the transpositions that iterative deepening naturally revisits.
        """
        if time.perf_counter() >= deadline:
            raise _TimeUp()

        if state.scores.get(my_id, 0.0) == 1.0:
            return WIN_SCORE + depth
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -WIN_SCORE - depth
        if depth == 0:
            return self._evaluate(state, my_id, opponent_id)

        alpha_orig, beta_orig = alpha, beta
        tt_key = (hash(state.rep), state.active_player.id, depth)
        cached = self._tt.get(tt_key)
        tt_move_key = None

        if cached is not None:
            cached_value, cached_flag, cached_move_key = cached
            tt_move_key = cached_move_key
            if cached_flag == "EXACT":
                return cached_value
            if cached_flag == "LOWERBOUND":
                alpha = max(alpha, cached_value)
            elif cached_flag == "UPPERBOUND":
                beta = min(beta, cached_value)
            if alpha >= beta:
                return cached_value

        actions = self._candidate_actions(state)
        actions = self._order_actions(state, actions, tt_move_key)

        best_value = -inf if maximizing else inf
        best_key = None

        for action in actions:
            child = state.apply_action(action)
            value = self._alphabeta(child, depth - 1, alpha, beta, not maximizing, my_id, opponent_id, deadline)

            if maximizing:
                if value > best_value:
                    best_value = value
                    best_key = self._action_key(action)
                alpha = max(alpha, value)
            else:
                if value < best_value:
                    best_value = value
                    best_key = self._action_key(action)
                beta = min(beta, value)

            if alpha >= beta:
                break

        # A cutoff means best_value only bounds the true value, not equals it:
        # fail-high (>= beta_orig) gives a lower bound, fail-low (<= alpha_orig)
        # an upper bound. Only a value that stayed strictly inside the original
        # window is exact.
        if best_value <= alpha_orig:
            flag = "UPPERBOUND"
        elif best_value >= beta_orig:
            flag = "LOWERBOUND"
        else:
            flag = "EXACT"

        self._store_tt(tt_key, best_value, flag, best_key)
        return best_value

    def _store_tt(self, key: tuple, value: float, flag: str, action_key: tuple | None) -> None:
        if len(self._tt) >= MAX_TT_ENTRIES:
            self._tt.clear()
        self._tt[key] = (value, flag, action_key)

    # ------------------------------------------------------------------
    # Action generation restricted to the moves worth searching
    # ------------------------------------------------------------------

    def _candidate_actions(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...] | None = None,
    ) -> list[Action]:
        """
        Keeps every pawn move, and only the walls that touch the opponent's
        or our own current shortest path.

        Checking legality of all ~128 wall placements (two BFS runs each, via
        `_is_wall_legal`) at every node of the tree would collapse the
        achievable search depth to 1-2. Restricting candidates to walls that
        can actually affect a shortest path keeps the branching factor small
        while still covering every action worth considering.
        """
        moves = list(state._legal_moves())

        active_id = state.active_player.id
        if state.rep.remaining_walls.get(active_id, 0) <= 0:
            return moves

        me = state.active_player
        opponent = self._opponent(state, me)
        opponent_path = self._shortest_path_positions(state, opponent)
        my_path = self._shortest_path_positions(state, me)

        seen = set()
        wall_candidates = []

        def collect(path):
            if not path or len(path) < 2:
                return
            for start, end in zip(path, path[1:]):
                for wall in state._candidate_blocking_walls(start, end):
                    key = (wall.row, wall.col, wall.orientation)
                    if key not in seen:
                        seen.add(key)
                        wall_candidates.append(wall)

        collect(opponent_path)
        collect(my_path)

        walls = []
        if legal_actions is not None:
            legal_lookup = {
                (a.data["type"], a.data["destination"]): a
                for a in legal_actions if a.data["type"] != "move"
            }
            for wall in wall_candidates:
                action_type = "vertical" if wall.orientation == Orientation.VERTICAL else "horizontal"
                action = legal_lookup.get((action_type, (wall.row, wall.col)))
                if action is not None:
                    walls.append(action)
        else:
            for wall in wall_candidates:
                if state._is_wall_legal(wall):
                    action_type = "vertical" if wall.orientation == Orientation.VERTICAL else "horizontal"
                    walls.append(StatelessAction({"type": action_type, "destination": (wall.row, wall.col)}))

        return moves + walls[:MAX_WALL_CANDIDATES]

    def _order_actions(self, state: GameStateQuoridor, actions: list[Action], tt_move_key: tuple | None) -> list[Action]:
        """
        Cheap move ordering to improve alpha-beta cutoffs: the transposition
        table's best move first, then pawn moves by how much closer they get
        to the goal row, then walls in the order `_candidate_actions` found
        them (opponent-blocking walls before path-protecting ones).
        """
        goal_row = state.active_player.get_goal_row()
        current_row, _ = state.rep.pawn_positions[state.active_player.id]

        def score(action: Action) -> float:
            if tt_move_key is not None and self._action_key(action) == tt_move_key:
                return 1_000.0
            if action.data["type"] == "move":
                new_row, _ = action.data["destination"]
                return 10.0 + (abs(current_row - goal_row) - abs(new_row - goal_row))
            return 0.0

        return sorted(actions, key=score, reverse=True)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, state: GameStateQuoridor, my_id: int, opponent_id: int) -> float:
        """
        Higher is better for my_id. Distances come from BFS on the board graph.
        """
        if state.scores.get(my_id, 0.0) == 1.0:
            return WIN_SCORE
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -WIN_SCORE

        me = self._player_by_id(state, my_id)
        opponent = self._player_by_id(state, opponent_id)

        my_distance = state._shortest_path(me)
        opponent_distance = state._shortest_path(opponent)

        if my_distance is None:
            return -NO_PATH_SCORE
        if opponent_distance is None:
            return NO_PATH_SCORE

        my_walls = state.rep.remaining_walls.get(my_id, 0)
        opponent_walls = state.rep.remaining_walls.get(opponent_id, 0)

        return (
            W_DISTANCE * (opponent_distance - my_distance)
            + W_WALLS * (my_walls - opponent_walls)
            + W_MOBILITY * (self._mobility(state, me) - self._mobility(state, opponent))
        )

    def _best_shallow_action(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...],
        my_id: int,
        opponent_id: int,
    ) -> Action:
        """
        Best action after a single ply of lookahead. Always cheap enough to
        finish even when almost no time budget remains, so it acts as a safe
        fallback if the deeper search gets interrupted immediately.
        """
        best_action = legal_actions[0]
        best_score = -inf

        for action in legal_actions:
            score = self._evaluate(state.apply_action(action), my_id, opponent_id)
            if score > best_score:
                best_score = score
                best_action = action

        return best_action

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _shortest_path_positions(self, state: GameStateQuoridor, player: Player) -> list[tuple[int, int]] | None:
        """
        BFS path reconstruction (ignoring the opponent pawn, like the engine's
        own `_shortest_path`) used to pick meaningful wall candidates.
        """
        start = state.rep.pawn_positions[player.id]
        goal_row = player.get_goal_row()
        queue = deque([start])
        visited = {start}
        parent = {start: None}

        while queue:
            position = queue.popleft()
            if position[0] == goal_row:
                path = []
                while position is not None:
                    path.append(position)
                    position = parent[position]
                path.reverse()
                return path

            for neighbour in state._reachable_neighbours(position):
                if neighbour not in visited:
                    visited.add(neighbour)
                    parent[neighbour] = position
                    queue.append(neighbour)

        return None

    def _mobility(self, state: GameStateQuoridor, player: Player) -> int:
        """
        Count simple reachable neighbours around a pawn, ignoring jump rules.
        """
        return len(state._reachable_neighbours(state.rep.pawn_positions[player.id]))

    def _opponent(self, state: GameStateQuoridor, player: Player) -> Player:
        return next(other for other in state.players if other.id != player.id)

    def _player_by_id(self, state: GameStateQuoridor, player_id: int) -> Player:
        return next(player for player in state.players if player.id == player_id)

    @staticmethod
    def _action_key(action: Action) -> tuple:
        return (action.data["type"], action.data["destination"])
