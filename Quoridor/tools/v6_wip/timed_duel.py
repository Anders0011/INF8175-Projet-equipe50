"""Timed matches (real time management, scaled-down clock) between parameter sets of one agent file.
    python timed_duel.py <quoridor_dir> <agent.py> <clock_seconds> <games> <workers> <seed> NAME=k:v,... -- A:B ...
Every time constant of the agent is scaled by clock/900, so a 90 s game is a 15-minute game in miniature.
Float parameters are allowed (MAX_MOVE_BUDGET:40).
A game in which one move overran its budget by more than SUSPECT_OVERRUN seconds is reported as
suspect (machine suspension or heavy contention) and left out of the score.
"""
import multiprocessing
import random
import sys
import time
from pathlib import Path

quoridor_dir = sys.argv[1]
sys.path.insert(0, str(Path(quoridor_dir) / "tools"))
import local_search  # noqa: E402

SUSPECT_OVERRUN = 2.0
TIME_CONSTANTS = ("SAFETY_MARGIN", "MIN_BUDGET", "MAX_MOVE_BUDGET", "QUIET_OPENING_BUDGET", "RACE_BUDGET")


def play(task):
    agent_path, params_a, params_b, seed, a_is_white, clock = task
    scale = clock / 900.0
    modules = []
    for params in (params_a, params_b):
        scaled = dict(params)
        base = local_search.load_agent_module(agent_path, {})
        for name in TIME_CONSTANTS:
            scaled[name] = round(params.get(name, getattr(base, name)) * scale, 4)
        modules.append(local_search.load_agent_module(agent_path, scaled))
    module_a, module_b = modules
    white_module, black_module = (module_a, module_b) if a_is_white else (module_b, module_a)
    white = white_module.MyPlayer("W", goal_row=0, name="white")
    black = black_module.MyPlayer("B", goal_row=8, name="black")
    position = local_search._Position(white.id, black.id)
    seats = {white.id: (white, white_module), black.id: (black, black_module)}
    clocks = {white.id: float(clock), black.id: float(clock)}
    rng = random.Random(seed)
    for _ in range(local_search.OPENING_PLIES):
        mover_id = position.active_player.id
        board = module_a._Board(position, mover_id)
        moves = board.pawn_destinations(0)
        if rng.random() < local_search.OPENING_WALL_PROBABILITY:
            walls = [code for code in range(board.size, 3 * board.size) if board.wall_legal(code)]
            if walls:
                moves = walls
        position.play(rng.choice(moves))
    depths = {white.id: [], black.id: []}
    overrun = 0.0
    while position.step < local_search.MAX_PLIES:
        mover_id = position.active_player.id
        agent, module = seats[mover_id]
        start = time.perf_counter()
        agent._record_position(position)
        board = module._Board(position, mover_id)
        budget = agent._time_budget(board, clocks[mover_id], position.step)
        moves = agent._root_moves(board)
        if not moves:
            return 0.5, 0, 0, 0, 0, overrun
        if len(moves) == 1:
            move = moves[0]
        else:
            move = agent._search(board, moves, start, budget)
            depths[mover_id].append(agent._reached_depth)
        spent = time.perf_counter() - start
        overrun = max(overrun, spent - budget)
        clocks[mover_id] -= spent
        a_id = white.id if a_is_white else black.id
        b_id = black.id if a_is_white else white.id
        if clocks[mover_id] <= 0:
            return (0.0 if mover_id == a_id else 1.0), clock - clocks[a_id], clock - clocks[b_id], -1, -1, overrun
        if position.play(move):
            score = 1.0 if mover_id == a_id else 0.0
            mean = lambda xs: sum(xs) / len(xs) if xs else 0
            return score, clock - clocks[a_id], clock - clocks[b_id], mean(depths[a_id]), mean(depths[b_id]), overrun
    return 0.5, 0, 0, 0, 0, overrun


def main() -> None:
    agent, clock, games, workers, seed = sys.argv[2], float(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
    rest = sys.argv[7:]
    split = rest.index("--")
    variants = {}
    for item in rest[:split]:
        name, spec = item.split("=")
        variants[name] = {k: (float(v) if "." in v else int(v)) for k, v in (pair.split(":") for pair in spec.split(","))} if spec else {}
    pool = multiprocessing.Pool(workers)
    for pairing in rest[split + 1:]:
        a, b = pairing.split(":")
        tasks = []
        for pair in range(games // 2):
            tasks.append((agent, variants[a], variants[b], seed * 1_000_000 + pair, True, clock))
            tasks.append((agent, variants[a], variants[b], seed * 1_000_000 + pair, False, clock))
        start = time.perf_counter()
        results = list(pool.imap(play, tasks, chunksize=1))
        suspect = sum(1 for r in results if r[5] > SUSPECT_OVERRUN)
        worst = max(r[5] for r in results)
        # drop a whole opening pair if either of its games is suspect, to keep the pairing
        keep = [i for i in range(0, len(results), 2)
                if results[i][5] <= SUSPECT_OVERRUN and results[i + 1][5] <= SUSPECT_OVERRUN]
        results = [results[j] for i in keep for j in (i, i + 1)]
        if not results:
            print(f"{a} vs {b}: every game suspect (worst overrun {worst:.1f}s)", flush=True)
            continue
        scores = [r[0] for r in results]
        pairs = [scores[i] + scores[i + 1] - 1 for i in range(0, len(scores), 2)]
        mean = sum(pairs) / len(pairs)
        sd = (sum((p - mean) ** 2 for p in pairs) / max(1, len(pairs) - 1)) ** 0.5
        margin = 100 * 1.96 * sd / len(pairs) ** 0.5 / 2
        flags = sum(1 for r in results if r[3] == -1)
        n = len(results)
        print(f"{a:8s} vs {b:8s} clock {clock:g}s: {sum(scores):g}/{n} = {100 * sum(scores) / n:5.1f}%  (+-{margin:.0f})  "
              f"time used {sum(r[1] for r in results) / n:.0f}s vs {sum(r[2] for r in results) / n:.0f}s, "
              f"mean depth {sum(r[3] for r in results) / n:.1f} vs {sum(r[4] for r in results) / n:.1f}, "
              f"losses on time {flags}, suspect games {suspect} (worst overrun {worst:.2f}s)  "
              f"[{time.perf_counter() - start:.0f}s]", flush=True)


if __name__ == "__main__":
    main()
