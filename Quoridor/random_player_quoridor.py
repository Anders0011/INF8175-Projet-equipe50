import random

from actions_quoridor import StatelessAction
from game_state_quoridor import GameStateQuoridor
from player_quoridor import PlayerQuoridor


class MyPlayer(PlayerQuoridor):
    """
    Player selecting uniformly a random legal action.
    """
    def __init__(self, piece_type: str, goal_row: int = 0, name: str = "bob", *args, **kwargs) -> None:
        """
        Initializes a new instance of the MyPlayer class.

        Args:
            piece_type (str): The type of the player's game piece.
            name (str, optional): The name of the player. Defaults to "bob".
        """
        super().__init__(piece_type, goal_row, name, *args, **kwargs)

    def compute_action(self, current_state: GameStateQuoridor, **kwargs) -> StatelessAction:
        """
        Selects and returns a uniformly random legal action.

        Attributes
            current_state (GameStateQuoridor): Current game state.

        Returns
            StatelessAction: A uniformly random legal action.
        """
        print(f"Computing action for player {self.get_id()} with piece type {self.get_piece_type()} and goal row {self.get_goal_row()}")
        actions = tuple(current_state.generate_possible_stateless_actions())

        if not actions:
            raise RuntimeError("No legal action available.")

        return random.choice(actions)