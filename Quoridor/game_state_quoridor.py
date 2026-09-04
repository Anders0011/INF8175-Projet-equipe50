from __future__ import annotations

import json
from typing import Dict, Generator, List, Optional
from collections import deque

from board_quoridor import BoardQuoridor
from actions_quoridor import MoveAction, WallAction, Wall, Orientation
from player_quoridor import PlayerQuoridor

from seahorse.game.game_state import GameState
from seahorse.game.stateless_action import StatelessAction
from seahorse.game.stateful_action import StatefulAction
from seahorse.player.player import Player
from seahorse.utils.serializer import Serializable


class GameStateQuoridor(GameState):
    """
    Represents a state of a Quoridor game.

    This class contains the complete game logic. It is responsible for
    generating legal actions, applying actions, validating wall placements,
    computing scores and detecting terminal states.
    """

    DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1))

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, scores: Dict[int, float], active_player: Player, players: List[Player], rep: BoardQuoridor, step: int) -> None:
        """
        Creates a new game state.
        """
        super().__init__(scores, active_player, players, rep)
        self.step = step


    def get_step(self) -> int:
        """
        Returns the current turn number.
        """
        return self.step


    # ------------------------------------------------------------------
    # Game termination
    # ------------------------------------------------------------------

    def is_done(self) -> bool:
        """
        Returns True if the game has reached a terminal state.
        """
        return any(score == 1.0 for score in self.scores.values())

    # ------------------------------------------------------------------
    # Action generation
    # ------------------------------------------------------------------

    def generate_possible_stateless_actions(self) -> Generator[StatelessAction, None, None]:
        """
        Generates every legal action from the current position.
        """
        yield from self._legal_moves()
        yield from self._legal_walls()

    def generate_possible_stateful_actions(self) -> Generator[StatefulAction, None, None]:
        """
        Generates every stateful action
        by applying every legal stateless action.
        """
        for action in self.generate_possible_stateless_actions():
            yield StatefulAction(self, self.apply_action(action))

    def apply_action(self, action: StatelessAction) -> GameStateQuoridor:
        """
        Applies a stateless action and returns the resulting game state.
        """

        new_board = self._next_board(action)

        scores = {self.players[0].id: 0.0, self.players[1].id: 0.0}

        for player in self.players:
            if self._goal_reached(new_board, player):
                scores[player.id] = 1.0

        return GameStateQuoridor(scores=scores, active_player=self.compute_next_player(),
                                 players=self.players, rep=new_board, step=self.step + 1)


    def _next_board(self, action: StatelessAction) -> BoardQuoridor:
        """
        Builds the board resulting from the given action.

        Attributes
            action (StatelessAction): Action to apply.

        Returns
            BoardQuoridor: New immutable board resulting from the action.
        """

        pawn_positions = dict(self.rep.pawn_positions)
        remaining_walls = dict(self.rep.remaining_walls)
        walls = set(self.rep.walls)
        if action.data["type"] == "move":
            pawn_positions[self.active_player.id] = action.data["destination"]

        elif action.data["type"] == "vertical":
            walls.add(Wall(row=action.data["destination"][0], col=action.data["destination"][1], orientation=Orientation.VERTICAL))
            remaining_walls[self.active_player.id] -= 1
        elif action.data["type"] == "horizontal":
            walls.add(Wall(row=action.data["destination"][0], col=action.data["destination"][1], orientation=Orientation.HORIZONTAL))
            remaining_walls[self.active_player.id] -= 1
        else:
            raise ValueError("Unknown action type.")

        return BoardQuoridor(pawn_positions=pawn_positions, walls=frozenset(walls), remaining_walls=remaining_walls)


    # ------------------------------------------------------------------
    # GUI conversion
    # ------------------------------------------------------------------

    def convert_stateful_action_to_stateless_action(
        self,
        stateful_action: StatefulAction,
    ) -> StatelessAction:
        """
        Converts a stateful action into its corresponding stateless action.
        """
        raise NotImplementedError()

    def convert_gui_data_to_action_data(self, gui_data: dict) -> dict:
        """
        Converts GUI data into the format expected by the engine.
        """
        return {"type": gui_data["type"], "destination": tuple(gui_data["destination"])}


    # ------------------------------------------------------------------
    # Pawn movement
    # ------------------------------------------------------------------

    def _legal_moves(self) -> List[MoveAction]:
        """
        Computes every legal pawn move.
        """

        actions = []
        position = self.rep.pawn_positions[self.active_player.id]

        for direction in self.DIRECTIONS:
            for destination in self._try_direction(position, direction):
                actions.append(StatelessAction({"type": "move",
                                                "destination": destination}))

        return actions

    def _try_direction(self, position: tuple[int, int],
                       direction: tuple[int, int]) -> List[tuple[int, int]]:
        """
        Computes every legal destination obtained by moving in the given
        direction.
        Special moves like umping behind an opponent are also tried.
        """

        row, col = position
        r, c = direction

        new_r = row + r
        new_c = col + c

        if not (0 <= new_r < self.rep.dimension
                and 0 <= new_c < self.rep.dimension):
            return []

        if self._blocked_by_wall(position, (new_r, new_c)):
            return []

        opponent_position = self.rep.pawn_positions[self._opponent(self.active_player).id]

        if (new_r, new_c) == opponent_position:
            if not self._blocked_by_wall(opponent_position, (new_r + r, new_c + c)): # jump
                return self._try_direction(opponent_position, direction)
            elif r == 0:    # diagonal
                return self._try_direction(opponent_position, (-1,0)) + self._try_direction(opponent_position, (1,0))
            elif c == 0:
                return self._try_direction(opponent_position, (0,-1)) + self._try_direction(opponent_position, (0,1))

        return [(new_r, new_c)]

    def _reachable_neighbours(self, position: tuple[int, int]) -> List[tuple[int, int]]:
        """
        Returns every neighbouring square reachable from the given position,
        ignoring both players.

        This function is only used by the shortest-path algorithm.
        """

        neighbours = []
        row, col = position

        for r, c in self.DIRECTIONS:

            new_r = row + r
            new_c = col + c

            if (0 <= new_r < self.rep.dimension and 0 <= new_c < self.rep.dimension and not self._blocked_by_wall(position, (new_r, new_c))):
                neighbours.append((new_r, new_c))

        return neighbours


    def _candidate_blocking_walls(self, start: tuple[int, int], end: tuple[int, int]) -> List[Wall]:
        """
        Returns every wall that could block the movement between two
        adjacent squares.

        Attributes
        start (tuple[int, int]): Starting square
        end (tuple[int, int]): Destination square

        Returns
            List[Wall]: List containing one or two candidate walls.
        """

        start_row, start_col = start
        end_row, end_col = end

        if abs(start_row - end_row) + abs(start_col - end_col) != 1:
            raise ValueError("start and end must be adjacent squares.")
        
        walls = []

        # Moving south

        if end_row == start_row + 1:
            if start_col > 0:
                walls.append(Wall(start_row+1, start_col-1, Orientation.HORIZONTAL))

            if start_col < self.rep.dimension - 1:
                walls.append(Wall(start_row+1, start_col, Orientation.HORIZONTAL))

        # Moving north

        elif end_row == start_row - 1:
            if start_col > 0:
                walls.append(Wall(start_row, start_col - 1, Orientation.HORIZONTAL))

            if start_col < self.rep.dimension - 1:
                walls.append(Wall(start_row, start_col, Orientation.HORIZONTAL))

        # Moving east

        elif end_col == start_col + 1:
            if start_row > 0:
                walls.append(Wall(start_row-1, start_col+1, Orientation.VERTICAL))

            if start_row < self.rep.dimension - 1:
                walls.append(Wall(start_row, start_col+1, Orientation.VERTICAL))

        # Moving west

        else: # end_col == start_col - 1:
            if start_row > 0:
                walls.append(Wall(start_row-1, start_col, Orientation.VERTICAL))

            if start_row < self.rep.dimension - 1:
                walls.append(Wall(start_row, start_col, Orientation.VERTICAL))
        
        return walls
    
    def _blocked_by_wall(self, start: tuple[int, int], end: tuple[int, int]) -> bool:
        """
        Returns whether a wall blocks the movement between two adjacent squares.

        Attributes
            start (tuple[int, int]): Starting square.
            end (tuple[int, int]): Destination square. Must be adjacent to start.

        Returns
            bool: True if at least one wall blocks the movement.
        """
        
        return (any(wall in self.rep.walls for wall in self._candidate_blocking_walls(start, end))  or any(coord<0 for coord in end) or any(coord>=self.rep.dimension for coord in end))


    # ------------------------------------------------------------------
    # Wall placement
    # ------------------------------------------------------------------

    def _legal_walls(self) -> List[WallAction]:
        """
        Computes all legal wall placement actions
        """
        actions = []
        for row in range(self.rep.dimension):
            for col in range(self.rep.dimension):
                for orientation in Orientation:
                    wall = Wall(row, col, orientation)
                    if self._is_wall_legal(wall):
                        actions.append(StatelessAction({"type": "vertical" if orientation == Orientation.VERTICAL else "horizontal", "destination": (wall.row, wall.col)}))

        return actions

    def _is_wall_legal(self, wall: Wall) -> bool:
        """
        Returns whether the given wall can legally be placed by the active
        player.

        A wall is legal if:
            - the player still owns at least one wall,
            - the wall lies inside the board,
            - it does not overlap an existing wall,
            - it does not cross an existing wall,
            - it leaves at least one path to the goal for both players.
        """

        # No walls remaining.
        
        if self.rep.remaining_walls[self.active_player.id] == 0:
            return False

        # Wall outside the board.
        
        if wall.orientation == Orientation.HORIZONTAL and not(0 <= wall.col < self.rep.dimension - 1):
            return False
        
        if wall.orientation == Orientation.VERTICAL and not (0 <= wall.row < self.rep.dimension - 1):
            return False

        # Overlapping wall.
        if wall.orientation == Orientation.HORIZONTAL:
            overlap1 = Wall(wall.row, wall.col+1, Orientation.HORIZONTAL)
            overlap2 = Wall(wall.row, wall.col-1, Orientation.HORIZONTAL)
        else:
            overlap1 = Wall(wall.row-1, wall.col, Orientation.VERTICAL)
            overlap2 = Wall(wall.row+1, wall.col, Orientation.VERTICAL)

        if any(w in self.rep.walls for w in [wall, overlap1, overlap2]):
            return False

        # Crossing wall.
        if wall.orientation == Orientation.HORIZONTAL:
            crossing = Wall(wall.row-1, wall.col+1, Orientation.VERTICAL)
        else:
            crossing = Wall(wall.row+1, wall.col-1, Orientation.HORIZONTAL)
        if crossing in self.rep.walls:
            return False

        # Build the new board.
        
        remaining_walls = dict(self.rep.remaining_walls)
        remaining_walls[self.active_player.id] -= 1

        new_board = BoardQuoridor(pawn_positions=self.rep.pawn_positions, walls=self.rep.walls | {wall}, remaining_walls=remaining_walls)

        test_state = GameStateQuoridor(scores=self.scores, active_player=self.active_player, players=self.players, rep=new_board, step=self.step)
        
        # Both players must still have a path.
        
        for player in self.players:
            if test_state._shortest_path(player) is None:
                return False

        return True

    # ------------------------------------------------------------------
    # Path finding
    # ------------------------------------------------------------------


    def _shortest_path(self, player: Player) -> Optional[int]:
        """
        Computes the length of the shortest path between the player's pawn
        and its target row.

        The search ignores the opponent pawn and only considers the walls
        currently present on the board.

        Attributes
            player (Player): Player whose shortest path is computed.

        Returns
            Optional[int]: Length of the shortest path, or None if no path exists.
        """

        start = self.rep.pawn_positions[player.id]
        queue = deque([(start, 0)])
        visited = {start}

        while queue:

            position, distance = queue.popleft()
            if position[0] == player.get_goal_row():
                return distance

            for neighbour in self._reachable_neighbours(position):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, distance + 1))

        return None

    def _goal_reached(self, board: BoardQuoridor, player: Player) -> bool:
        """
        Returns True if the player has reached its target side.
        """
        row, _ = board.pawn_positions[player.id]
        return row == player.get_goal_row()


    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _opponent(self, player: Player) -> Player:
        """
        Returns the opponent of the given player.
        """
        return next(p for p in self.players if p.id != player.id)


    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_json(self) -> dict:
        """
        Serializes the game state.
        """
        data = {key: value for key, value in self.__dict__.items() if not key.startswith("_")}
        data["active_player"] = self.active_player.to_json()
        data["players"] = [player.to_json() for player in self.players]
        data["rep"] = self.rep.to_json()

        return data

    @staticmethod
    def from_json(
            data, *, active_player: Optional[PlayerQuoridor] = None
            ) -> Serializable:
        """
        Deserializes a game state.
        """

        if isinstance(data, str):
            data = json.loads(data)

        players = [PlayerQuoridor.from_json(player)
                   for player in data["players"]]

        if active_player is None:
            active_player_data = data.get("active_player")
            if active_player_data is not None:
                active_player = next(
                    (player for player in players
                     if player.get_id() == active_player_data["id"]),
                    PlayerQuoridor.from_json(active_player_data),
                )

        return GameStateQuoridor(
            scores={int(k): v for k, v in data["scores"].items()},
            active_player=active_player,
            players=players,
            rep=BoardQuoridor.from_json(data["rep"]),
            step=data["step"],
        )
