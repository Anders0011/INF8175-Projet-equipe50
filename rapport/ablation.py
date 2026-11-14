"""
Pruning ablation for the report: nodes needed to finish depth d, on positions
taken from V5 self-play, for
  minimax   plain minimax tree over the same move generator (counted, not evaluated)
  strict    PVS/alpha-beta, table used at equal depth only, no mirror, no reductions
  table     + full table reuse (deeper entries, mirror keys), no reductions
  full      + late-move reductions (the shipped agent)
Counts are cumulative over the iterative-deepening passes 1..d for the three
search variants (that is what the agent really pays), and the single depth-d
tree for minimax (which is generous to minimax).
"""
import json
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent / "Quoridor"
sys.path.insert(0, str(QUORIDOR_DIR))

from board_quoridor import BoardQuoridor  # noqa: E402
from game_state_quoridor import GameStateQuoridor  # noqa: E402
import my_player  # noqa: E402
from my_player import MyPlayer, _Board  # noqa: E402

OUT = Path(__file__).with_name("ablation.json")
SAMPLE_PLIES = (8, 14, 20, 26)
GAMES = 4
MINIMAX_DEPTH = 4
SEARCH_DEPTH = {"strict": 6, "table": 6, "full": 8}


def positions():
    """Positions from depth-3 self-play of the shipped agent, two random pawn plies first."""
    out = []
    for game in range(GAMES):
        rng = random.Random(100 + game)
        white = MyPlayer("W", goal_row=0, name="w")
        black = MyPlayer("B", goal_row=8, name="b")
        players = {white.id: white, black.id: black}
        rep = BoardQuoridor({white.id: (8, 4), black.id: (0, 4)}, frozenset(),
                            {white.id: 10, black.id: 10})
        state = GameStateQuoridor({white.id: 0, black.id: 0}, white, [white, black], rep, step=0)
        for ply in range(max(SAMPLE_PLIES) + 1):
            if state.is_done():
                break
            if ply in SAMPLE_PLIES:
                out.append(state)
            if ply < 2:
                moves = [a for a in state.generate_possible_stateless_actions()
                         if a.data["type"] == "move"]
                state = state.apply_action(rng.choice(moves))
                continue
            agent = players[state.active_player.id]
            board = _Board(state, state.active_player.id)
            moves = agent._root_moves(board)
            best = agent._search(board, moves, time.perf_counter(), 1e9, max_depth=3)
            state = state.apply_action(agent._to_engine_action(board, best, state))
    return out


def count_minimax(agent, board, depth):
    """Nodes of the unpruned tree of this depth (root excluded, like the agent's counter)."""
    turn = board.turn
    other = 1 - turn
    if board.geo.row_of[board.pawns[other]] == board.goals[other] or depth == 0:
        return 0
    pawn_moves = board.pawn_destinations(turn)
    walls = [code for code in agent._wall_candidates(board, board.shortest_path(turn),
                                                     board.shortest_path(other))
             if board.wall_legal(code)]
    total = len(pawn_moves) + len(walls)
    if depth == 1:
        return total
    for cell in pawn_moves:
        previous = board.make_move(cell)
        total += count_minimax(agent, board, depth - 1)
        board.unmake_move(previous)
    for code in walls:
        board.make_wall(code)
        total += count_minimax(agent, board, depth - 1)
        board.unmake_wall(code)
    return total


def measure(args):
    index, state = args
    me = state.active_player
    result = {"index": index, "step": state.step, "walls_on_board": len(state.rep.get_env()) if hasattr(state.rep, "get_env") else None}

    agent = MyPlayer("W", goal_row=me.get_goal_row(), name="t")
    result["minimax"] = [count_minimax(agent, _Board(state, me.id), d)
                         for d in range(1, MINIMAX_DEPTH + 1)]

    for variant, max_depth in SEARCH_DEPTH.items():
        MyPlayer._strict = variant == "strict"
        MyPlayer._reductions = variant == "full"
        agent = MyPlayer("W", goal_row=me.get_goal_row(), name="t")
        agent._deadline = time.perf_counter() + 1e9
        agent._killers = [[-1, -1] for _ in range(my_player.MAX_DEPTH + 2)]
        agent._history = [0] * (3 * state.rep.dimension ** 2)
        agent._nodes = 0
        agent._next_clock_check = 1 << 60
        board = _Board(state, me.id)
        moves = agent._root_moves(board)
        nodes, seconds, chosen = [], [], []
        start = time.perf_counter()
        for depth in range(1, max_depth + 1):
            best, value = agent._search_root(board, moves, depth)
            moves = [best] + [m for m in moves if m != best]
            nodes.append(agent._nodes)
            seconds.append(round(time.perf_counter() - start, 3))
            chosen.append(best)
            if abs(value) >= my_player.WIN_SCORE:
                break
        result[variant] = {"nodes": nodes, "seconds": seconds, "move": chosen}
    MyPlayer._strict, MyPlayer._reductions = False, True
    return result


if __name__ == "__main__":
    states = positions()
    print(f"{len(states)} positions", flush=True)
    results = []
    with Pool(4) as pool:
        for row in pool.imap_unordered(measure, list(enumerate(states))):
            results.append(row)
            print(f"position {row['index']} (ply {row['step']}): minimax {row['minimax']} "
                  f"full {row['full']['nodes']}", flush=True)
            OUT.write_text(json.dumps(sorted(results, key=lambda r: r["index"]), indent=1))
    print("done")
