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
MAX_MOVE_BUDGET = 30.0     # no single move may claim more than this, whatever the estimate says
MAX_BUDGET_FRACTION = 0.2  # nor more than this share of the time left, so the tail can never run dry
MIN_MOVES_LEFT = 12        # floor on the remaining-move estimate, for the same reason
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
        # The clock starts here, not after the setup below: everything this
        # method does counts against the move's budget.
        start = time.perf_counter()

        me = current_state.active_player
        opponent = self._opponent(current_state, me)
        deadline = start + self._time_budget(current_state, me, opponent, remaining_time)

        actions = self._candidate_actions(current_state)
        if not actions:
            actions = list(current_state.generate_possible_stateless_actions())
            if not actions:
                raise RuntimeError("No legal action available.")
        if len(actions) == 1:
            return actions[0]

        # Cheap guaranteed fallback. Depth 1 of the search below refines it
        # almost immediately, so it only has to be legal and sane, not good.
        best_action = self._fallback_action(current_state, actions, me)

        depth = 1
        try:
            while depth <= MAX_DEPTH:
                action, _ = self._search_root(current_state, actions, depth, me.id, opponent.id, deadline)
                if action is not None:
                    best_action = action
                depth += 1
        except _TimeUp:
            pass

        return best_action

    def _time_budget(self, state: GameStateQuoridor, me: Player, opponent: Player, remaining_time: float) -> float:
        """
        Share of the whole-game budget granted to this move.

        Estimated from my own remaining turns (at best one row per turn, plus
        the turns spent placing walls). Three caps keep a single move from
        ever claiming an absurd slice: an absolute ceiling, a fraction of what
        is left, and a floor under the remaining-move estimate. Without them
        an endgame estimate of "4 moves left" granted 225s for one move.
        """
        if remaining_time <= SAFETY_MARGIN:
            return 0.0

        my_distance = state._shortest_path(me) or 0
        my_walls = state.rep.remaining_walls.get(me.id, 0)
        moves_left_estimate = max(MIN_MOVES_LEFT, my_distance + my_walls)

        usable = remaining_time - SAFETY_MARGIN
        budget = min(usable / moves_left_estimate, MAX_MOVE_BUDGET, usable * MAX_BUDGET_FRACTION)
        return max(min(MIN_BUDGET, usable), budget)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search_root(
        self,
        state: GameStateQuoridor,
        actions: list[Action],
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

    def _candidate_actions(self, state: GameStateQuoridor) -> list[Action]:
        """
        Keeps every pawn move, and only the walls that touch the opponent's
        or our own current shortest path.

        Checking legality of all ~128 wall placements (two BFS runs each, via
        `_is_wall_legal`) at every node of the tree would collapse the
        achievable search depth to 1-2. Restricting candidates to walls that
        can actually affect a shortest path keeps the branching factor small
        while still covering every action worth considering. This is also why
        the root calls it instead of `generate_possible_stateless_actions`,
        which costs ~270ms a turn to enumerate walls we would discard anyway.
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

    def _fallback_action(self, state: GameStateQuoridor, actions: list[Action], me: Player) -> Action:
        """
        The pawn move that gets closest to the goal, or any legal action if
        none advances. Only a handful of BFS runs, so it still completes when
        the budget is nearly zero — unlike a full one-ply scan of every
        action, which cost ~450ms a turn and blew the budget on its own.
        """
        best_action = actions[0]
        best_distance = inf

        for action in actions:
            if action.data["type"] != "move":
                continue
            child = state.apply_action(action)
            distance = child._shortest_path(self._player_by_id(child, me.id))
            if distance is None:
                continue
            if distance < best_distance:
                best_distance = distance
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
