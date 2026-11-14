"""
Search test: the optimised search must return the plain minimax value.

`my_player.py` layers a lot on top of minimax: null-window (principal
variation) search, a transposition table, killer/history ordering, wall
legality established lazily, and distances inherited from the parent node
instead of recomputed. Every one of those is supposed to change the SPEED
of the search and nothing else. This checks exactly that: on sampled
positions, at fixed depths, the fast search must give the same root value
as `reference()` below -- a negamax with no pruning, no table, every wall
checked up front and every distance recomputed from scratch.

Late-move reductions are the one deliberate exception (they trade exactness
for depth), so they are switched off here, along with table reuse across
depths and across mirror positions, through `MyPlayer._strict` and
`MyPlayer._reductions`.

RUN THIS AFTER ANY CHANGE TO THE SEARCH. A wrong sign or a wrong bound does
not crash: it just plays slightly worse, and no match is long enough to show it.

Usage:
    python tools/test_search.py [positions] [max_depth]
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))

from board_quoridor import BoardQuoridor  # noqa: E402
from game_state_quoridor import GameStateQuoridor  # noqa: E402
import my_player  # noqa: E402
from my_player import MyPlayer, _Board, TEMPO, W_DISTANCE, W_WALLS, WIN_SCORE  # noqa: E402


def static_value(board: _Board) -> int:
    turn = board.turn
    return (W_DISTANCE * (board.distance(1 - turn) - board.distance(turn))
            + W_WALLS * (board.walls_left[turn] - board.walls_left[1 - turn]) + TEMPO)


def reference(agent: MyPlayer, board: _Board, depth: int) -> int:
    """Plain negamax over the same move generator, nothing clever."""
    turn = board.turn
    other = 1 - turn
    if board.geo.row_of[board.pawns[other]] == board.goals[other]:
        return -(WIN_SCORE + depth)
    if depth == 0:
        return static_value(board)

    best = None
    for cell in board.pawn_destinations(turn):
        previous = board.make_move(cell)
        value = -reference(agent, board, depth - 1)
        board.unmake_move(previous)
        if best is None or value > best:
            best = value
    walls = agent._wall_candidates(board, board.shortest_path(turn), board.shortest_path(other))
    for code in walls:
        if not board.wall_legal(code):
            continue
        board.make_wall(code)
        value = -reference(agent, board, depth - 1)
        board.unmake_wall(code)
        if best is None or value > best:
            best = value
    return static_value(board) if best is None else best


def sample_positions(count: int, seed: int, wall_bias: float = 0.35):
    """Positions from semi-random play, so walls accumulate like in a real game."""
    rng = random.Random(seed)
    out = []
    while len(out) < count:
        p1 = MyPlayer("W", goal_row=0, name="a")
        p2 = MyPlayer("B", goal_row=8, name="b")
        rep = BoardQuoridor({p1.id: (8, 4), p2.id: (0, 4)}, frozenset(), {p1.id: 10, p2.id: 10})
        state = GameStateQuoridor({p1.id: 0, p2.id: 0}, p1, [p1, p2], rep, step=0)
        while not state.is_done() and state.step < 70 and len(out) < count:
            actions = list(state.generate_possible_stateless_actions())
            moves = [a for a in actions if a.data["type"] == "move"]
            walls = [a for a in actions if a.data["type"] != "move"]
            pool = walls if (walls and rng.random() < wall_bias) else moves
            state = state.apply_action(rng.choice(pool or actions))
            if not state.is_done() and rng.random() < 0.25:
                out.append(state)
    return out


def main(positions: int, max_depth: int) -> None:
    MyPlayer._strict = True
    MyPlayer._reductions = False
    my_player.GAIN_ORDER_MIN_DEPTH = 2  # so the gain-ordered branch is exercised at these depths

    failures = 0
    checked = 0
    start = time.perf_counter()
    for index, state in enumerate(sample_positions(positions, seed=7)):
        me = state.active_player
        expected = {}
        for depth in range(1, max_depth + 1):
            board = _Board(state, me.id)
            agent = MyPlayer("W", goal_row=me.get_goal_row(), name="t")
            moves = agent._root_moves(board)
            if not moves:
                break
            best = None
            for move in moves:
                if move < board.size:
                    previous = board.make_move(move)
                    value = -reference(agent, board, depth - 1)
                    board.unmake_move(previous)
                else:
                    board.make_wall(move)
                    value = -reference(agent, board, depth - 1)
                    board.unmake_wall(move)
                best = value if best is None else max(best, value)
            expected[depth] = best

        # One agent across all depths, like the real iterative deepening, so
        # table entries left by shallower passes are in play.
        agent = MyPlayer("W", goal_row=me.get_goal_row(), name="t")
        agent._deadline = time.perf_counter() + 1e9
        agent._killers = [[-1, -1] for _ in range(my_player.MAX_DEPTH + 2)]
        agent._history = [0] * (3 * state.rep.dimension ** 2)
        for depth, want in expected.items():
            board = _Board(state, me.id)
            moves = agent._root_moves(board)
            _, got = agent._search_root(board, moves, depth)
            checked += 1
            if got != want:
                failures += 1
                if failures <= 10:
                    print(f"MISMATCH position {index} (step {state.step}) depth {depth}: "
                          f"search {got}, minimax {want}")

    elapsed = time.perf_counter() - start
    print(f"checked {checked} (position, depth) pairs in {elapsed:.0f}s")
    if failures:
        print(f"FAILURES: {failures}")
        raise SystemExit(1)
    print("ALL CHECKS PASSED: the search returns the minimax value")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40,
         int(sys.argv[2]) if len(sys.argv) > 2 else 3)
