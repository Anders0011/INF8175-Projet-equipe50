"""Fixed-depth matches between parameter sets of one agent file, all on the SAME paired openings.
    python duel.py <quoridor_dir> <agent.py> <depth> <games> <workers> <seed> NAME=k:v,k:v ... -- A:B A:B ...
"""
import multiprocessing
import sys
import time
from pathlib import Path

quoridor_dir = sys.argv[1]
sys.path.insert(0, str(Path(quoridor_dir) / "tools"))
import local_search  # noqa: E402


def main() -> None:
    agent, depth, games, workers, seed = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
    rest = sys.argv[7:]
    split = rest.index("--")
    variants = {}
    for item in rest[:split]:
        name, spec = item.split("=")
        variants[name] = {k: int(v) for k, v in (pair.split(":") for pair in spec.split(","))} if spec else {}
    pool = multiprocessing.Pool(workers)
    for pairing in rest[split + 1:]:
        a, b = pairing.split(":")
        tasks = []
        for pair in range(games // 2):
            tasks.append((agent, variants[a], variants[b], seed * 1_000_000 + pair, True, depth))
            tasks.append((agent, variants[a], variants[b], seed * 1_000_000 + pair, False, depth))
        start = time.perf_counter()
        results = list(pool.imap(local_search.play_game, tasks, chunksize=1))
        score = sum(results)
        rate = score / len(tasks)
        # paired openings: the unit of evidence is the opening (two games), not the game
        pairs = [results[i] + results[i + 1] - 1 for i in range(0, len(results), 2)]
        mean = sum(pairs) / len(pairs)
        sd = (sum((p - mean) ** 2 for p in pairs) / max(1, len(pairs) - 1)) ** 0.5
        margin = 100 * 1.96 * sd / len(pairs) ** 0.5 / 2
        print(f"{a:8s} vs {b:8s} depth {depth}: {score:g}/{len(tasks)} = {100 * rate:5.1f}%  (+-{margin:.0f})  "
              f"[{time.perf_counter() - start:.0f}s]", flush=True)


if __name__ == "__main__":
    main()
