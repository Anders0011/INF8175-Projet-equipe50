"""
Differential test: the agent's fast board must agree with the engine exactly.

The agent reimplements the game rules for speed, so any divergence means an
illegal action and an instant loss. RUN THIS AFTER ANY CHANGE TO `_Board`.

At every sampled position it checks:
  - pawn destinations match the engine's _legal_moves() (jumps, diagonals)
  - wall legality matches _is_wall_legal() for EVERY slot on the board
  - distances match the engine's _shortest_path()
  - make/unmake restores the board exactly, Zobrist hash included
  - every candidate the agent generates really is legal per the engine
  - worst_wall_damage() leaves the board untouched (it mutates and restores)

Usage:
    python tools/test_rules.py [games]
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))

from actions_quoridor import Orientation, Wall  # noqa: E402
from board_quoridor import BoardQuoridor  # noqa: E402
from game_state_quoridor import GameStateQuoridor  # noqa: E402
from my_player import MyPlayer, _Board  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)
        if len(FAILURES) > 20:
            print("too many failures:")
            for failure in FAILURES:
                print("  " + failure)
            raise SystemExit(1)


def snapshot(board: _Board):
    return (list(board.blocked), set(board.h_walls), set(board.v_walls),
            list(board.pawns), list(board.walls_left), board.turn,
            board.hash, board.hash_mirror)


def compare(state: GameStateQuoridor, tag: str) -> None:
    me = state.active_player
    other = next(p for p in state.players if p.id != me.id)
    board = _Board(state, me.id)
    dim = state.rep.dimension
    probe = MyPlayer("W", goal_row=me.get_goal_row(), name="t")

    engine_moves = {a.data["destination"] for a in state._legal_moves()}
    fast_moves = {(c // dim, c % dim) for c in board.pawn_destinations(0)}
    check(engine_moves == fast_moves,
          f"{tag}: moves differ engine={sorted(engine_moves)} fast={sorted(fast_moves)}")

    for row in range(dim):
        for col in range(dim):
            for is_h, orientation in ((True, Orientation.HORIZONTAL), (False, Orientation.VERTICAL)):
                engine_ok = state._is_wall_legal(Wall(row, col, orientation))
                fast_ok = board.wall_legal(is_h, row, col)
                check(engine_ok == fast_ok,
                      f"{tag}: wall {'H' if is_h else 'V'}({row},{col}) "
                      f"engine={engine_ok} fast={fast_ok}")

    check(board.distance(0) == state._shortest_path(me), f"{tag}: distance p0 differs")
    check(board.distance(1) == state._shortest_path(other), f"{tag}: distance p1 differs")

    # worst_wall_damage places and removes walls internally; it must restore.
    before = snapshot(board)
    damage = board.worst_wall_damage(0, 1)
    check(snapshot(board) == before, f"{tag}: worst_wall_damage corrupted the board")
    check(damage >= 0, f"{tag}: negative damage {damage}")

    before = snapshot(board)
    for action in probe._candidate_actions(board):
        undo = probe._make(board, action)
        expected_hash, expected_mirror = board._full_hashes()
        check(board.hash == expected_hash, f"{tag}: hash desync after {action}")
        check(board.hash_mirror == expected_mirror,
              f"{tag}: MIRROR hash desync after {action}")
        probe._unmake(board, action, undo)
        check(snapshot(board) == before, f"{tag}: unmake did not restore after {action}")

        if action[0] == "wall":
            orientation = Orientation.HORIZONTAL if action[1] else Orientation.VERTICAL
            check(state._is_wall_legal(Wall(action[2], action[3], orientation)),
                  f"{tag}: generated ILLEGAL wall {action}")
        else:
            check((action[1] // dim, action[1] % dim) in engine_moves,
                  f"{tag}: generated ILLEGAL move {action}")


def main(games: int) -> None:
    rng = random.Random(1)
    checked = 0
    for game in range(games):
        p1 = MyPlayer("W", goal_row=0, name="a")
        p2 = MyPlayer("B", goal_row=8, name="b")
        rep = BoardQuoridor({p1.id: (8, 4), p2.id: (0, 4)}, frozenset(), {p1.id: 10, p2.id: 10})
        state = GameStateQuoridor({p1.id: 0, p2.id: 0}, p1, [p1, p2], rep, step=0)
        while not state.is_done() and state.step < 60:
            compare(state, f"g{game}s{state.step}")
            checked += 1
            state = state.apply_action(rng.choice(list(state.generate_possible_stateless_actions())))

    print(f"checked {checked} positions")
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for failure in FAILURES[:20]:
            print("  " + failure)
        raise SystemExit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
