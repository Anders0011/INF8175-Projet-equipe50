"""
Differential test: the agent's fast board must agree with the engine exactly.

The agent reimplements the game rules for speed, so any divergence means an
illegal action and an instant loss. RUN THIS AFTER ANY CHANGE TO `_Board`.

At every sampled position it checks:
  - pawn destinations match the engine's _legal_moves() (jumps, diagonals)
  - wall legality matches _is_wall_legal() for EVERY slot on the board
  - distances match the engine's _shortest_path()
  - make/unmake restores the board exactly, both Zobrist hashes included
  - every root move the agent generates really is legal per the engine
  - shortest_path() agrees with distance(), and a wall that closes no crossing
    of a player's shortest path really leaves that player's distance unchanged
    (the search relies on this to skip path searches)

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
    return (list(board.blocked), bytes(board.occupied),
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

    geo = board.geo
    for row in range(dim):
        for col in range(dim):
            for is_h, orientation in ((True, Orientation.HORIZONTAL), (False, Orientation.VERTICAL)):
                engine_ok = state._is_wall_legal(Wall(row, col, orientation))
                code = geo.h_code(row, col) if is_h else geo.v_code(row, col)
                fast_ok = board.wall_legal(code)
                check(engine_ok == fast_ok,
                      f"{tag}: wall {'H' if is_h else 'V'}({row},{col}) "
                      f"engine={engine_ok} fast={fast_ok}")

    distances = [board.distance(0), board.distance(1)]
    check(distances[0] == state._shortest_path(me), f"{tag}: distance p0 differs")
    check(distances[1] == state._shortest_path(other), f"{tag}: distance p1 differs")

    paths = [board.shortest_path(0), board.shortest_path(1)]
    crossings = [board.crossings(paths[0]), board.crossings(paths[1])]
    for player in (0, 1):
        check(len(paths[player]) - 1 == distances[player], f"{tag}: path length p{player} differs")
        check(board.has_path(player), f"{tag}: has_path p{player} is False on a legal position")

    # The shortcut the search depends on: a wall that closes no crossing of a
    # shortest path cannot change that player's distance.
    before = snapshot(board)
    for code in probe._wall_candidates(board, paths[0], paths[1]):
        board.place(code)
        for player in (0, 1):
            if geo.wall_cuts[code].isdisjoint(crossings[player]):
                check(board.distance(player) == distances[player],
                      f"{tag}: wall {code} misses p{player}'s path but changed its distance")
        board.remove(code)
    check(snapshot(board) == before, f"{tag}: place/remove did not restore the board")

    size = board.size
    for move in probe._root_moves(board):
        if move < size:
            previous = board.make_move(move)
        else:
            board.make_wall(move)
        expected_hash, expected_mirror = board._full_hashes()
        check(board.hash == expected_hash, f"{tag}: hash desync after {move}")
        check(board.hash_mirror == expected_mirror, f"{tag}: MIRROR hash desync after {move}")
        if move < size:
            board.unmake_move(previous)
        else:
            board.unmake_wall(move)
        check(snapshot(board) == before, f"{tag}: unmake did not restore after {move}")

        if move < size:
            check((move // dim, move % dim) in engine_moves, f"{tag}: generated ILLEGAL move {move}")
        else:
            orientation = Orientation.HORIZONTAL if move < 2 * size else Orientation.VERTICAL
            row, col = divmod(move % size, dim)
            check(state._is_wall_legal(Wall(row, col, orientation)),
                  f"{tag}: generated ILLEGAL wall {move}")

    # Mirror table: mirroring twice is the identity wherever it is defined.
    for code in range(3 * size):
        image = geo.mirror_move[code]
        if image >= 0:
            check(geo.mirror_move[image] == code, f"{tag}: mirror of mirror of {code} is not itself")


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
