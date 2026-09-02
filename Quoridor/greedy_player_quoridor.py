import random

from actions_quoridor import StatelessAction
from game_state_quoridor import GameStateQuoridor
from player_quoridor import PlayerQuoridor


class MyPlayer(PlayerQuoridor):
    """
    Player selecting a legal action based on a direct heuristic evaluation.
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
        Selects and returns a greedy action. The heuristic evaluation of a state s is computed as
            H(s) = d(active_player) - d(other_player) 
        where d(player) is the minimal number of moves required by a player to reach the other side of the board.
        the selected action is the one that minimizes H(s).
        100 is always an acceptable upper bound given the board size

        Attributes
            current_state (GameStateQuoridor): Current game state.

        Returns
            StatelessAction: A uniformly random legal action.
        """
        actions = tuple(current_state.generate_possible_stateless_actions())

        if not actions:
            raise RuntimeError("No legal action available.")

        best_action = None
        best_cost = 100

        for action in actions:
            temp_state = current_state.apply_action(action)
            cost = temp_state._shortest_path(temp_state.players[0]) - temp_state._shortest_path(temp_state.players[1])

            if current_state.active_player.id == current_state.players[1].id:
                cost *= -1
                
            if cost < best_cost:
                best_cost = cost
                best_action = action

        return best_action
