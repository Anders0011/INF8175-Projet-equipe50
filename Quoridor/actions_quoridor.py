from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from seahorse.game.stateless_action import StatelessAction


class Orientation(Enum):
    """
    Orientation of a wall
    """
    HORIZONTAL = "H"
    VERTICAL = "V"


@dataclass(frozen=True, order=True)
class Wall:
    """
    Represents a wall on the board. The coordinates are the cell at the lower-right (south-east) corner of the coordinates.
    Feasible wall placement coordinates should then live in ([0:8], [0:8])

    Attributes:
        row (int): Placement row
        col (int): Placement column
        orientation (Orientation): Horizontal or vertical.
    """
    row: int
    col: int
    orientation: Orientation


class QuoridorAction(StatelessAction):
    """
    Base class for every Quoridor action.
    """

    pass


class MoveAction(QuoridorAction):
    """
    Move the pawn to a new position.
    """

    def __init__(self, destination: tuple[int, int]) -> None:
        super().__init__({"destination": destination})

    @property
    def destination(self) -> tuple[int, int]:
        return self.data["destination"]

    def __repr__(self) -> str:
        return f"MoveAction(destination={self.destination})"


class WallAction(QuoridorAction):
    """
    Place a wall.
    """

    def __init__(self, wall: Wall) -> None:
        super().__init__({"wall": wall})

    @property
    def wall(self) -> Wall:
        return self.data["wall"]

    def __repr__(self) -> str:
        return f"WallAction({self.wall})"