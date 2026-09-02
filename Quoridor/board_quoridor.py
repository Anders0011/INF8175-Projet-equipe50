from __future__ import annotations

import json
from dataclasses import dataclass, field

from seahorse.game.game_layout.board import Board
from seahorse.utils.serializer import Serializable

from actions_quoridor import Wall, Orientation


class BoardQuoridor(Board):
    """
    A class representing a Quoridor board.

    Attributes
        pawn_positions (dict[int, tuple[int, int]]): Current position of each player's pawn.
        walls (frozenset[Wall]): Set of walls currently placed on the board.
        remaining_walls (dict[int, int]): Number of walls still available for each player.
        dimension (int): grid size
    """

    def __init__(self, pawn_positions: dict[int, tuple[int, int]], walls: set[Wall], remaining_walls: dict[int, int], dimension: int = 9) -> None:
        """
        Initializes the parent Board class.

        Because the dataclass is frozen, object.__setattr__ is required.
        """
        super().__init__(env={}, dim=[dimension, dimension])
        self.pawn_positions = pawn_positions
        self.walls = walls 
        self.remaining_walls = remaining_walls
        self.dimension = dimension

    def __str__(self) -> str:
        """
        Returns a simple textual representation of the board.

        This representation is mainly intended for debugging purposes.
        """

        grid = [["." for _ in range(self.dimension)] for _ in range(self.dimension)]

        #
        # Place the pawns.
        #

        for player_id, (row, col) in self.pawn_positions.items():
            grid[row][col] = str(player_id % 100)

        lines = []

        #
        # Header
        #

        header = "    " + " ".join(chr(ord("a") + c) for c in range(self.dimension))
        # header = "    " + "  ".join(str(c+1) for c in range(self.dimension))
        lines.append(header)

        #
        # Board
        #

        for row in range(self.dimension):
            lines.append(f"{row + 1:2d}  " + " ".join(f"{cell:>2}" for cell in grid[row]))

        #
        # Walls
        #

        horizontal = sorted(
            wall for wall in self.walls
            if wall.orientation == Orientation.HORIZONTAL
        )

        vertical = sorted(
            wall for wall in self.walls
            if wall.orientation == Orientation.VERTICAL
        )

        lines.append("")
        lines.append("Horizontal walls:")

        if horizontal:
            for wall in horizontal:
                # lines.append(f"  ({wall.col+1}, {wall.row + 1})")
                lines.append(f"  ({chr(ord("a") + wall.col)}, {wall.row + 1})")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("Vertical walls:")

        if vertical:
            for wall in vertical:
                # lines.append(f"  ({wall.col+1}, {wall.row + 1})")
                lines.append(f"  ({chr(ord("a") + wall.col)}, {wall.row + 1})")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("Remaining walls:")

        for player_id, remaining in sorted(self.remaining_walls.items()):
            lines.append(f"  Player {player_id}: {remaining}")

        return "\n".join(lines)
    
    def __hash__(self):
        return hash((frozenset(self.pawn_positions.items()), self.walls, frozenset(self.remaining_walls.items()),self.dimension))
    
    def __eq__(self, other):
        if not isinstance(other, BoardQuoridor):
            return NotImplemented
        return (self.pawn_positions == other.pawn_positions and self.walls == other.walls and self.remaining_walls == other.remaining_walls and self.dimension == other.dimension)


    def to_json(self) -> dict:
        """
        Converts the board to a JSON object.

        Returns:
            dict: The JSON representation of the board.
        """
        return {
            "pawn_positions": {str(player_id): list(position) for player_id, position in self.pawn_positions.items()},
            "walls": [{"row": wall.row, "col": wall.col, "orientation": wall.orientation.value,} for wall in self.walls],
            "remaining_walls": {str(player_id): remaining for player_id, remaining in self.remaining_walls.items()},
            "dimension": self.dimension
        }

    @staticmethod
    def from_json(data) -> Serializable:
        """
        Deserializes a BoardQuoridor.
        """
        if isinstance(data, str):
            data = json.loads(data)

        pawn_positions = {int(player_id): tuple(position) for player_id, position in data["pawn_positions"].items()}
        walls = frozenset(Wall(row=wall["row"], col=wall["col"], orientation=Orientation(wall["orientation"])) for wall in data["walls"])
        remaining_walls = {int(player_id): remaining for player_id, remaining in data["remaining_walls"].items()}
        dimension = int(data.get("dimension"))

        return BoardQuoridor(pawn_positions=pawn_positions, walls=walls, remaining_walls=remaining_walls, dimension=dimension)