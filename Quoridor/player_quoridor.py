from __future__ import annotations

import json

from seahorse.player.player import Player
from seahorse.utils.serializer import Serializable


class PlayerQuoridor(Player):
    """
    Represents a player in a Quoridor game.

    Attributes
        piece_type (str): piece type of the player
    """

    def __init__(self, piece_type: str, goal_row: int = 0, name: str = "bob", *args, **kwargs) -> None:
        """
        Initializes a new instance of the PlayerQuoridor class.

        Args:
            piece_type (str): The type of the player's game piece.
            name (str, optional): The name of the player. Defaults to "bob".
        """
        super().__init__(name, *args, **kwargs)
        self.piece_type = piece_type # Black or White
        self.goal_row = goal_row


    def get_piece_type(self) -> str:
        """
        Gets the type of the player's game piece.

        Returns:
            str: The type of the player's game piece.
        """
        return self.piece_type
    
    def get_goal_row(self) -> str:
        """
        Gets the row number of the player's goal.

        Returns:
            int: The goal row id.
        """
        return self.goal_row

    def set_piece_type(self, piece_type: str) -> None:
        """
        Sets the type of the player's game piece.

        Args:
            piece_type (str): The type of the player's game piece.
        """
        if piece_type not in ["W", "B"]:
            raise ValueError("Piece type must be 'W' or 'B'.")
        self.piece_type = piece_type

    def to_json(self) -> dict:
        return {i: j for i, j in self.__dict__.items() if not i.startswith("_")}

    @staticmethod
    def from_json(data) -> Serializable:
        if isinstance(data, str):
            data = json.loads(data)

        return PlayerQuoridor(**data)