from __future__ import annotations

import time
from collections import deque
from math import inf, log1p

from actions_quoridor import Orientation
from game_state_quoridor import GameStateQuoridor
from player_quoridor import PlayerQuoridor
from seahorse.game.action import Action
from seahorse.game.stateless_action import StatelessAction
from seahorse.player.player import Player


class _TimeUp(Exception):
    pass


W_DISTANCE = 25.0
W_PATHS = 1.2
W_WALLS = 2.0
W_MOBILITY = 0.25
W_PROGRESS = 0.8

WIN_SCORE = 1_000_000.0
NO_PATH_SCORE = 500_000.0

SAFETY_MARGIN = 1.0
MIN_BUDGET = 0.05
MAX_WALL_CANDIDATES = 28
MAX_TT_ENTRIES = 200_000
MAX_DEPTH = 30
MAX_PATH_COUNT = 100_000
HISTORY_LENGTH = 8
QUIESCENCE_DEPTH = 2


class MyPlayer(PlayerQuoridor):
    """Iterative-deepening minimax player with alpha-beta and board heuristics."""

    def __init__(self, piece_type: str, goal_row: int = 0, name: str = "bob", *args, **kwargs) -> None:
        super().__init__(piece_type, goal_row, name, *args, **kwargs)
        self._tt = {}
        self._recent_positions: deque[tuple[int, int]] = deque(maxlen=HISTORY_LENGTH)
        self._last_game_step: int | None = None

    def compute_action(self, current_state: GameStateQuoridor, remaining_time: float = 15 * 60, **kwargs) -> Action:
        legal_actions = tuple(current_state.generate_possible_stateless_actions())
        if not legal_actions:
            raise RuntimeError("No legal action available.")
        if len(legal_actions) == 1:
            return legal_actions[0]

        self._record_position(current_state)
        me = current_state.active_player
        opponent = self._opponent(current_state, me)
        best_action = self._best_shallow_action(current_state, legal_actions, me.id, opponent.id)
        deadline = time.perf_counter() + self._time_budget(current_state, me, opponent, remaining_time)

        depth = 1
        try:
            while depth <= MAX_DEPTH:
                action, _ = self._search_root(
                    current_state, legal_actions, depth, me.id, opponent.id, deadline
                )
                if action is not None:
                    best_action = action
                depth += 1
        except _TimeUp:
            pass

        return best_action

    def _record_position(self, state: GameStateQuoridor) -> None:
        if self._last_game_step is not None and state.get_step() < self._last_game_step:
            self._recent_positions.clear()
            self._tt.clear()
        self._last_game_step = state.get_step()
        position = state.rep.pawn_positions[self.id]
        if not self._recent_positions or self._recent_positions[-1] != position:
            self._recent_positions.append(position)

    def _time_budget(self, state: GameStateQuoridor, me: Player, opponent: Player, remaining_time: float) -> float:
        if remaining_time <= SAFETY_MARGIN:
            return 0.0
        my_distance = state._shortest_path(me) or 0
        opponent_distance = state._shortest_path(opponent) or 0
        walls_left = state.rep.remaining_walls.get(me.id, 0) + state.rep.remaining_walls.get(opponent.id, 0)
        moves_left_estimate = max(4, my_distance + opponent_distance + walls_left // 2)
        usable = remaining_time - SAFETY_MARGIN
        return max(MIN_BUDGET, min(usable / moves_left_estimate, usable * 0.5))

    def _search_root(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...],
        depth: int,
        my_id: int,
        opponent_id: int,
        deadline: float,
    ) -> tuple[Action | None, float]:
        # Search every legal root action so useful walls are not discarded.
        actions = list(legal_actions)
        tt_key, mirrored = self._state_key(state, my_id, opponent_id, depth)
        cached = self._tt.get(tt_key)
        tt_move_key = cached[2] if cached else None
        actions = self._order_actions(state, actions, tt_move_key, mirrored, my_id, opponent_id)

        alpha, beta = -inf, inf
        best_action = None
        best_value = -inf
        best_tiebreak = None

        for action in actions:
            child = state.apply_action(action)
            value = self._alphabeta(child, depth - 1, alpha, beta, False, my_id, opponent_id, deadline)
            value += self._repetition_penalty(action)
            tiebreak = self._tie_break(state, action, child, my_id, opponent_id)

            if value > best_value or (abs(value - best_value) <= 1e-9 and tiebreak > (best_tiebreak or ())):
                best_value = value
                best_action = action
                best_tiebreak = tiebreak
            alpha = max(alpha, value)

        if best_action is not None:
            canonical_move = self._canonical_action_key(best_action, state.rep.dimension, mirrored)
            self._store_tt(tt_key, best_value, "EXACT", canonical_move)
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
        if time.perf_counter() >= deadline:
            raise _TimeUp()
        if state.scores.get(my_id, 0.0) == 1.0:
            return WIN_SCORE + depth
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -WIN_SCORE - depth
        if depth == 0:
            return self._quiescence(
                state, alpha, beta, maximizing, my_id, opponent_id, deadline,
                QUIESCENCE_DEPTH,
            )

        alpha_orig, beta_orig = alpha, beta
        tt_key, mirrored = self._state_key(state, my_id, opponent_id, depth)
        cached = self._tt.get(tt_key)
        tt_move_key = None
        if cached is not None:
            cached_value, cached_flag, tt_move_key = cached
            if cached_flag == "EXACT":
                return cached_value
            if cached_flag == "LOWERBOUND":
                alpha = max(alpha, cached_value)
            elif cached_flag == "UPPERBOUND":
                beta = min(beta, cached_value)
            if alpha >= beta:
                return cached_value

        actions = self._candidate_actions(state)
        actions = self._order_actions(state, actions, tt_move_key, mirrored, my_id, opponent_id)
        best_value = -inf if maximizing else inf
        best_key = None

        for action in actions:
            value = self._alphabeta(
                state.apply_action(action), depth - 1, alpha, beta,
                not maximizing, my_id, opponent_id, deadline
            )
            if maximizing:
                if value > best_value:
                    best_value = value
                    best_key = self._canonical_action_key(action, state.rep.dimension, mirrored)
                alpha = max(alpha, value)
            else:
                if value < best_value:
                    best_value = value
                    best_key = self._canonical_action_key(action, state.rep.dimension, mirrored)
                beta = min(beta, value)
            if alpha >= beta:
                break

        if best_value <= alpha_orig:
            flag = "UPPERBOUND"
        elif best_value >= beta_orig:
            flag = "LOWERBOUND"
        else:
            flag = "EXACT"
        self._store_tt(tt_key, best_value, flag, best_key)
        return best_value

    def _quiescence(
        self,
        state: GameStateQuoridor,
        alpha: float,
        beta: float,
        maximizing: bool,
        my_id: int,
        opponent_id: int,
        deadline: float,
        depth: int,
    ) -> float:
        """Resolve immediate goals before trusting a static leaf evaluation."""
        if time.perf_counter() >= deadline:
            raise _TimeUp()
        if state.scores.get(my_id, 0.0) == 1.0:
            return WIN_SCORE + depth
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -WIN_SCORE - depth

        me = self._player_by_id(state, my_id)
        opponent = self._player_by_id(state, opponent_id)
        my_distance = state._shortest_path(me)
        opponent_distance = state._shortest_path(opponent)
        tactical = (my_distance is not None and my_distance <= 1) or (
            opponent_distance is not None and opponent_distance <= 1
        )
        if depth == 0 or not tactical:
            return self._evaluate(state, my_id, opponent_id)

        actions = list(state._legal_moves())
        if not actions:
            return self._evaluate(state, my_id, opponent_id)

        if maximizing:
            value = -inf
            for action in actions:
                value = max(value, self._quiescence(
                    state.apply_action(action), alpha, beta, False,
                    my_id, opponent_id, deadline, depth - 1
                ))
                alpha = max(alpha, value)
                if alpha >= beta:
                    break
            return value

        value = inf
        for action in actions:
            value = min(value, self._quiescence(
                state.apply_action(action), alpha, beta, True,
                my_id, opponent_id, deadline, depth - 1
            ))
            beta = min(beta, value)
            if alpha >= beta:
                break
        return value

    def _store_tt(self, key: tuple, value: float, flag: str, action_key: tuple | None) -> None:
        if len(self._tt) >= MAX_TT_ENTRIES:
            self._tt.clear()
        self._tt[key] = (value, flag, action_key)

    def _candidate_actions(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...] | None = None,
    ) -> list[Action]:
        moves = list(state._legal_moves())
        active_id = state.active_player.id
        if state.rep.remaining_walls.get(active_id, 0) <= 0:
            return moves

        me = state.active_player
        opponent = self._opponent(state, me)
        seen = set()
        wall_candidates = []
        for player in (opponent, me):
            for start, end in self._optimal_path_edges(state, player):
                for wall in state._candidate_blocking_walls(start, end):
                    key = (wall.row, wall.col, wall.orientation)
                    if key not in seen:
                        seen.add(key)
                        wall_candidates.append(wall)

        if legal_actions is not None:
            legal_lookup = {
                (a.data["type"], a.data["destination"]): a
                for a in legal_actions if a.data["type"] != "move"
            }
            walls = []
            for wall in wall_candidates:
                action_type = "vertical" if wall.orientation == Orientation.VERTICAL else "horizontal"
                action = legal_lookup.get((action_type, (wall.row, wall.col)))
                if action is not None:
                    walls.append(action)
        else:
            walls = []
            for wall in wall_candidates:
                if state._is_wall_legal(wall):
                    action_type = "vertical" if wall.orientation == Orientation.VERTICAL else "horizontal"
                    walls.append(StatelessAction({"type": action_type, "destination": (wall.row, wall.col)}))
        return moves + walls[:MAX_WALL_CANDIDATES]

    def _order_actions(
        self,
        state: GameStateQuoridor,
        actions: list[Action],
        tt_move_key: tuple | None,
        mirrored: bool,
        my_id: int,
        opponent_id: int,
    ) -> list[Action]:
        dimension = state.rep.dimension

        def score(action: Action) -> tuple:
            canonical_key = self._canonical_action_key(action, dimension, mirrored)
            if tt_move_key is not None and canonical_key == tt_move_key:
                return (10000.0, 0.0, 0.0, 0.0)
            if action.data["type"] == "move":
                row, _ = action.data["destination"]
                goal_row = state.active_player.get_goal_row()
                current_row, _ = state.rep.pawn_positions[state.active_player.id]
                progress = abs(current_row - goal_row) - abs(row - goal_row)
                winning = 1.0 if row == goal_row else 0.0
                return (3.0 + winning, progress, -self._repetition_cost(action), 0.0)
            return (1.0, 0.0, -self._repetition_cost(action), 0.0)

        return sorted(actions, key=score, reverse=True)

    def _evaluate(self, state: GameStateQuoridor, my_id: int, opponent_id: int) -> float:
        if state.scores.get(my_id, 0.0) == 1.0:
            return WIN_SCORE
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -WIN_SCORE

        me = self._player_by_id(state, my_id)
        opponent = self._player_by_id(state, opponent_id)
        my_stats = self._route_stats(state, me)
        opponent_stats = self._route_stats(state, opponent)
        my_distance, my_paths = my_stats[0], my_stats[1]
        opponent_distance, opponent_paths = opponent_stats[0], opponent_stats[1]

        if my_distance is None:
            return -NO_PATH_SCORE
        if opponent_distance is None:
            return NO_PATH_SCORE

        my_walls = state.rep.remaining_walls.get(my_id, 0)
        opponent_walls = state.rep.remaining_walls.get(opponent_id, 0)
        my_row, _ = state.rep.pawn_positions[my_id]
        opponent_row, _ = state.rep.pawn_positions[opponent_id]
        my_progress = my_row if me.get_goal_row() == 0 else state.rep.dimension - 1 - my_row
        opponent_progress = opponent_row if opponent.get_goal_row() == 0 else state.rep.dimension - 1 - opponent_row

        return (
            W_DISTANCE * (opponent_distance - my_distance)
            + W_PATHS * (log1p(my_paths) - log1p(opponent_paths))
            + W_WALLS * (my_walls - opponent_walls)
            + W_MOBILITY * (self._mobility(state, me) - self._mobility(state, opponent))
            + W_PROGRESS * (my_progress - opponent_progress)
        )

    def _best_shallow_action(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...],
        my_id: int,
        opponent_id: int,
    ) -> Action:
        best_action = legal_actions[0]
        best_score = -inf
        best_tiebreak = ()
        actions = list(legal_actions)
        for action in actions:
            child = state.apply_action(action)
            score = self._evaluate(child, my_id, opponent_id) + self._repetition_penalty(action)
            tiebreak = self._tie_break(state, action, child, my_id, opponent_id)
            if score > best_score or (abs(score - best_score) <= 1e-9 and tiebreak > best_tiebreak):
                best_score = score
                best_action = action
                best_tiebreak = tiebreak
        return best_action

    def _route_stats(self, state: GameStateQuoridor, player: Player) -> tuple[int | None, int, dict, dict]:
        start = state.rep.pawn_positions[player.id]
        goal_row = player.get_goal_row()
        distances = {start: 0}
        counts = {start: 1}
        queue = deque([start])
        while queue:
            position = queue.popleft()
            for neighbour in state._reachable_neighbours(position):
                candidate_distance = distances[position] + 1
                if neighbour not in distances:
                    distances[neighbour] = candidate_distance
                    counts[neighbour] = counts[position]
                    queue.append(neighbour)
                elif distances[neighbour] == candidate_distance:
                    counts[neighbour] = min(MAX_PATH_COUNT, counts[neighbour] + counts[position])

        goal_positions = [position for position in distances if position[0] == goal_row]
        if not goal_positions:
            return None, 0, distances, {}
        distance = min(distances[position] for position in goal_positions)
        paths = min(
            MAX_PATH_COUNT,
            sum(counts[position] for position in goal_positions if distances[position] == distance),
        )
        return distance, paths, distances, counts

    def _optimal_path_edges(self, state: GameStateQuoridor, player: Player) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        distance, _, distances, _ = self._route_stats(state, player)
        if distance is None:
            return []
        goal_row = player.get_goal_row()
        goals = [(0, col) if goal_row == 0 else (state.rep.dimension - 1, col)
                 for col in range(state.rep.dimension)]
        reverse = {}
        queue = deque([goal for goal in goals if goal in distances])
        for goal in queue:
            reverse[goal] = 0
        while queue:
            position = queue.popleft()
            for neighbour in state._reachable_neighbours(position):
                if neighbour not in reverse:
                    reverse[neighbour] = reverse[position] + 1
                    queue.append(neighbour)

        edges = []
        for position, position_distance in distances.items():
            if position_distance >= distance:
                continue
            for neighbour in state._reachable_neighbours(position):
                if position_distance + 1 + reverse.get(neighbour, inf) == distance:
                    edges.append((position, neighbour))
        return edges

    def _repetition_cost(self, action: Action) -> float:
        if action.data["type"] != "move":
            return 0.0
        destination = tuple(action.data["destination"])
        return self._position_cost(destination)

    def _position_cost(self, position: tuple[int, int]) -> float:
        recent = list(self._recent_positions)
        if not recent:
            return 0.0
        cost = 0.0
        if position == recent[-1]:
            cost += 20.0
        if position in recent[-4:]:
            cost += 5.0 * (4 - recent[-4:].index(position))
        if len(recent) >= 2 and position == recent[-2] and recent[-1] != recent[-2]:
            cost += 16.0
        return cost

    def _repetition_penalty(self, action: Action) -> float:
        return -self._repetition_cost(action)

    def _tie_break(
        self,
        state: GameStateQuoridor,
        action: Action,
        child: GameStateQuoridor,
        my_id: int,
        opponent_id: int,
    ) -> tuple:
        me = self._player_by_id(child, my_id)
        opponent = self._player_by_id(child, opponent_id)
        my_distance = child._shortest_path(me)
        opponent_distance = child._shortest_path(opponent)
        _, my_paths, _, _ = self._route_stats(child, me)
        return (
            1 if child.scores.get(my_id, 0.0) == 1.0 else 0,
            -(my_distance if my_distance is not None else 999),
            opponent_distance if opponent_distance is not None else -999,
            my_paths,
            -self._repetition_cost(action),
            1 if action.data["type"] == "move" else 0,
            tuple(action.data["destination"]),
        )

    def _state_key(self, state: GameStateQuoridor, my_id: int, opponent_id: int, depth: int) -> tuple[tuple, bool]:
        raw, mirrored = self._board_key(state, my_id, opponent_id)
        canonical = min(raw, mirrored)
        return (canonical, state.active_player.id, my_id, opponent_id, depth), raw != canonical

    def _board_key(self, state: GameStateQuoridor, my_id: int, opponent_id: int) -> tuple[tuple, tuple]:
        dimension = state.rep.dimension
        positions = tuple(sorted(state.rep.pawn_positions.items()))
        mirrored_positions = tuple(sorted((pid, (row, dimension - 1 - col)) for pid, (row, col) in positions))
        walls = tuple(sorted((wall.row, wall.col, wall.orientation.value) for wall in state.rep.walls))
        mirrored_walls = tuple(sorted(self._mirror_wall_key(wall, dimension) for wall in state.rep.walls))
        remaining = tuple(sorted(state.rep.remaining_walls.items()))
        raw = (positions, walls, remaining, dimension)
        mirrored = (mirrored_positions, mirrored_walls, remaining, dimension)
        return raw, mirrored

    @staticmethod
    def _mirror_wall_key(wall, dimension: int) -> tuple[int, int, str]:
        if wall.orientation == Orientation.HORIZONTAL:
            return wall.row, dimension - 2 - wall.col, wall.orientation.value
        return wall.row, dimension - 1 - wall.col, wall.orientation.value

    @staticmethod
    def _canonical_action_key(action: Action, dimension: int, mirrored: bool = False) -> tuple:
        action_type = action.data["type"]
        row, col = action.data["destination"]
        if mirrored:
            if action_type == "move":
                col = dimension - 1 - col
            elif action_type == "horizontal":
                col = dimension - 2 - col
            else:
                col = dimension - 1 - col
        return action_type, (row, col)

    def _mobility(self, state: GameStateQuoridor, player: Player) -> int:
        return len(state._reachable_neighbours(state.rep.pawn_positions[player.id]))

    def _opponent(self, state: GameStateQuoridor, player: Player) -> Player:
        return next(other for other in state.players if other.id != player.id)

    def _player_by_id(self, state: GameStateQuoridor, player_id: int) -> Player:
        return next(player for player in state.players if player.id == player_id)
