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


# Heuristic weights
W_DISTANCE = 25.0
W_WALLS = 2.0
W_MOBILITY = 0.2
W_REPETITION = 5.0  # Poids pour pénaliser les va-et-vient

WIN_SCORE = 1_000_000.0
NO_PATH_PENALTY = 999.0  # Remplace le short-circuit de V1 pour permettre le calcul de la mobilité

SAFETY_MARGIN = 1.0
MIN_BUDGET = 0.05
MAX_WALL_CANDIDATES = 24
MAX_TT_ENTRIES = 200_000
MAX_DEPTH = 30
HISTORY_LENGTH = 4  # Garder un historique court pour les répétitions


class MyPlayer(PlayerQuoridor):
    """
    Agent Quoridor optimal combinant la profondeur de recherche rapide de V1
    avec la protection contre les boucles infinies de V2.
    """

    def __init__(self, piece_type: str, goal_row: int = 0, name: str = "bob", *args, **kwargs) -> None:
        super().__init__(piece_type, goal_row, name, *args, **kwargs)
        self._tt = {}
        self._recent_positions: deque[tuple[int, int]] = deque(maxlen=HISTORY_LENGTH)
        self._last_game_step: int | None = None

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def compute_action(self, current_state: GameStateQuoridor, remaining_time: float = 15 * 60, **kwargs) -> Action:
        legal_actions = tuple(current_state.generate_possible_stateless_actions())
        if not legal_actions:
            raise RuntimeError("No legal action available.")
        if len(legal_actions) == 1:
            return legal_actions[0]

        # Enregistrement de la position pour détecter les boucles
        self._record_position(current_state)

        me = current_state.active_player
        opponent = self._opponent(current_state, me)

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

    def _record_position(self, state: GameStateQuoridor) -> None:
        """Conserve un historique récent pour pénaliser les retours en arrière."""
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
            
            # Application de la pénalité de répétition à la racine
            value -= self._repetition_cost(action) * W_REPETITION

            if value > best_value:
                best_value = value
                best_action = action
            alpha = max(alpha, value)

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
    # Action generation
    # ------------------------------------------------------------------

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
        goal_row = state.active_player.get_goal_row()
        current_row, _ = state.rep.pawn_positions[state.active_player.id]

        def score(action: Action) -> float:
            if tt_move_key is not None and self._action_key(action) == tt_move_key:
                return 1_000.0
            if action.data["type"] == "move":
                new_row, _ = action.data["destination"]
                # Soustraction de la pénalité de répétition pour éviter de boucler
                return 10.0 + (abs(current_row - goal_row) - abs(new_row - goal_row)) - self._repetition_cost(action)
            return 0.0

        return sorted(actions, key=score, reverse=True)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, state: GameStateQuoridor, my_id: int, opponent_id: int) -> float:
        """
        Calcule un score sans retourner de valeurs arbitraires, permettant à
        la mobilité de départager les coups quand une défaite s'annonce.
        """
        if state.scores.get(my_id, 0.0) == 1.0:
            return WIN_SCORE
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -WIN_SCORE

        me = self._player_by_id(state, my_id)
        opponent = self._player_by_id(state, opponent_id)

        my_dist_val = state._shortest_path(me)
        opp_dist_val = state._shortest_path(opponent)

        # Si le chemin est bloqué, on applique une lourde pénalité numérique
        # au lieu de court-circuiter complètement le calcul.
        my_distance = my_dist_val if my_dist_val is not None else NO_PATH_PENALTY
        opponent_distance = opp_dist_val if opp_dist_val is not None else NO_PATH_PENALTY

        my_walls = state.rep.remaining_walls.get(my_id, 0)
        opponent_walls = state.rep.remaining_walls.get(opponent_id, 0)

        # La mobilité reste active pour choisir la case avec le plus de sorties possibles
        return (
            W_DISTANCE * (opponent_distance - my_distance)
            + W_WALLS * (my_walls - opponent_walls)
            + W_MOBILITY * (self._mobility(state, me) - self._mobility(state, opponent))
        )

    def _repetition_cost(self, action: Action) -> float:
        """Détecte les coups en va-et-vient et retourne un coût multiplicateur."""
        if action.data["type"] != "move":
            return 0.0
        
        destination = tuple(action.data["destination"])
        recent = list(self._recent_positions)
        
        if not recent:
            return 0.0
            
        cost = 0.0
        if destination == recent[-1]:
            cost += 10.0
        if destination in recent:
            cost += 2.0 * (len(recent) - recent.index(destination))
            
        return cost

    def _best_shallow_action(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...],
        my_id: int,
        opponent_id: int,
    ) -> Action:
        best_action = legal_actions[0]
        best_score = -inf

        for action in legal_actions:
            score = self._evaluate(state.apply_action(action), my_id, opponent_id)
            score -= self._repetition_cost(action) * W_REPETITION
            
            if score > best_score:
                best_score = score
                best_action = action

        return best_action

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _shortest_path_positions(self, state: GameStateQuoridor, player: Player) -> list[tuple[int, int]] | None:
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
        return len(state._reachable_neighbours(state.rep.pawn_positions[player.id]))

    def _opponent(self, state: GameStateQuoridor, player: Player) -> Player:
        return next(other for other in state.players if other.id != player.id)

    def _player_by_id(self, state: GameStateQuoridor, player_id: int) -> Player:
        return next(player for player in state.players if player.id == player_id)

    @staticmethod
    def _action_key(action: Action) -> tuple:
        return (action.data["type"], action.data["destination"])