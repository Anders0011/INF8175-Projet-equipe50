from collections import deque
from math import inf

from game_state_quoridor import GameStateQuoridor
from player_quoridor import PlayerQuoridor
from seahorse.game.action import Action
from seahorse.player.player import Player

class MyPlayer(PlayerQuoridor):
    """
    Player class for Quoridor game

    Attributes:
        piece_type (str): piece type of the player
    """

    def __init__(self, piece_type: str, goal_row: int=0, name: str = "bob", *args, **kwargs) -> None:
        """
        Initialize the PlayerQuoridor instance.

        Args:
            piece_type (str): Type of the player's game piece
            goal_row (int): The row the player wants to reach
            name (str, optional): Name of the player (default is "bob")
        """
        super().__init__(piece_type, goal_row, name)

    def compute_action(self, current_state: GameStateQuoridor, remaining_time: float = 15*60, **kwargs) -> Action:
        """
        Choose a legal action with a one-ply BFS-based heuristic.

        Args:
            current_state (GameStateQuoridor): The current game state.

        Returns:
            Action: The selected legal action.
        """
        legal_actions = tuple(current_state.generate_possible_stateless_actions())
        if not legal_actions:
            raise RuntimeError("No legal action available.")

        me = current_state.active_player
        opponent = self._opponent(current_state, me)
        actions = self._candidate_actions(current_state, legal_actions, opponent)

        current_my_distance = self._shortest_path(current_state, me)
        current_opponent_distance = self._shortest_path(current_state, opponent)

        best_action = actions[0]
        best_score = -inf
        best_priority = -inf

        for action in actions:
            next_state = current_state.apply_action(action)
            score = self._evaluate_state(next_state, me.id, opponent.id)
            score += self._action_bonus(
                action,
                next_state,
                me.id,
                opponent.id,
                current_my_distance,
                current_opponent_distance,
            )
            priority = self._action_priority(action)

            if score > best_score or (score == best_score and priority > best_priority):
                best_score = score
                best_priority = priority
                best_action = action

        return best_action

    def _candidate_actions(
        self,
        state: GameStateQuoridor,
        legal_actions: tuple[Action, ...],
        opponent: Player,
    ) -> tuple[Action, ...]:
        """
        Keep all pawn moves, and only the walls that can disturb the
        opponent's current shortest path.
        """
        moves = [action for action in legal_actions if action.data["type"] == "move"]
        wall_actions = [action for action in legal_actions if action.data["type"] != "move"]

        if not wall_actions or state.rep.remaining_walls.get(state.active_player.id, 0) <= 0:
            return tuple(moves)

        opponent_path = self._shortest_path_positions(state, opponent)
        if not opponent_path or len(opponent_path) < 2:
            return tuple(moves)

        legal_walls_by_key = {
            (action.data["type"], action.data["destination"]): action
            for action in wall_actions
        }
        selected_walls = []
        seen = set()

        for start, end in zip(opponent_path, opponent_path[1:]):
            for wall in state._candidate_blocking_walls(start, end):
                action_type = "vertical" if wall.orientation.value == "V" else "horizontal"
                key = (action_type, (wall.row, wall.col))
                action = legal_walls_by_key.get(key)
                if action is not None and key not in seen:
                    selected_walls.append(action)
                    seen.add(key)

        if not selected_walls:
            selected_walls = wall_actions[:8]

        return tuple(moves + selected_walls)

    def _evaluate_state(self, state: GameStateQuoridor, my_id: int, opponent_id: int) -> float:
        """
        Higher is better for my_id. Distances come from BFS on the board graph.
        """
        if state.scores.get(my_id, 0.0) == 1.0:
            return 1_000_000.0
        if state.scores.get(opponent_id, 0.0) == 1.0:
            return -1_000_000.0

        me = self._player_by_id(state, my_id)
        opponent = self._player_by_id(state, opponent_id)

        my_distance = self._shortest_path(state, me)
        opponent_distance = self._shortest_path(state, opponent)

        if my_distance is None:
            return -500_000.0
        if opponent_distance is None:
            return 500_000.0

        my_walls = state.rep.remaining_walls.get(my_id, 0)
        opponent_walls = state.rep.remaining_walls.get(opponent_id, 0)

        return (
            25.0 * (opponent_distance - my_distance)
            + 2.0 * (my_walls - opponent_walls)
            + 0.2 * self._mobility(state, me)
            - 0.2 * self._mobility(state, opponent)
        )

    def _action_bonus(
        self,
        action: Action,
        state: GameStateQuoridor,
        my_id: int,
        opponent_id: int,
        previous_my_distance: int | None,
        previous_opponent_distance: int | None,
    ) -> float:
        """
        Small tie-breaking pressure: prefer useful walls and direct progress.
        """
        action_type = action.data["type"]

        me = self._player_by_id(state, my_id)
        opponent = self._player_by_id(state, opponent_id)
        my_distance = self._shortest_path(state, me)
        opponent_distance = self._shortest_path(state, opponent)

        if action_type == "move":
            if previous_my_distance is not None and my_distance is not None:
                return 1.5 * (previous_my_distance - my_distance)
            return 0.5

        bonus = -0.5
        if previous_opponent_distance is not None and opponent_distance is not None:
            bonus += 4.0 * (opponent_distance - previous_opponent_distance)
        if previous_my_distance is not None and my_distance is not None:
            bonus -= 2.0 * max(0, my_distance - previous_my_distance)
        return bonus

    def _shortest_path(self, state: GameStateQuoridor, player: Player) -> int | None:
        """
        Breadth-first search from the pawn to the player's goal row.

        All edges have cost 1, so BFS is also equivalent to UCS here.
        """
        start = state.rep.pawn_positions[player.id]
        queue = deque([(start, 0)])
        visited = {start}

        while queue:
            position, distance = queue.popleft()
            if position[0] == player.get_goal_row():
                return distance

            for neighbour in state._reachable_neighbours(position):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, distance + 1))

        return None

    def _shortest_path_positions(self, state: GameStateQuoridor, player: Player) -> list[tuple[int, int]] | None:
        """
        BFS path reconstruction used to pick meaningful wall candidates.
        """
        start = state.rep.pawn_positions[player.id]
        queue = deque([start])
        visited = {start}
        parent = {start: None}

        while queue:
            position = queue.popleft()
            if position[0] == player.get_goal_row():
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

    def _action_priority(self, action: Action) -> int:
        return 1 if action.data["type"] == "move" else 0
