"""
Analyse real Abyss games (the JSON downloads).

Reports, per game: who played, who won, how the time budget was actually
spent, and whether a pawn ever went backwards -- the signature of being
sealed off behind a wall barrier.

Abyss records `remaining_time` per player at every step, so the real
per-move cost is recoverable, including the server's own overhead. That is
the one thing local testing cannot measure.

Usage:
    python tools/analyse_games.py path/to/fight_*.json
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))


def blocked(walls, start, end, dim):
    """Mirror of the engine's wall semantics, on raw JSON walls."""
    (sr, sc), (er, ec) = start, end
    hwalls = {(w["row"], w["col"]) for w in walls if w["orientation"] == "H"}
    vwalls = {(w["row"], w["col"]) for w in walls if w["orientation"] == "V"}
    if er == sr + 1:
        return (sc > 0 and (sr + 1, sc - 1) in hwalls) or (sc < dim - 1 and (sr + 1, sc) in hwalls)
    if er == sr - 1:
        return (sc > 0 and (sr, sc - 1) in hwalls) or (sc < dim - 1 and (sr, sc) in hwalls)
    if ec == sc + 1:
        return (sr > 0 and (sr - 1, sc + 1) in vwalls) or (sr < dim - 1 and (sr, sc + 1) in vwalls)
    return (sr > 0 and (sr - 1, sc) in vwalls) or (sr < dim - 1 and (sr, sc) in vwalls)


def distance(rep, position, goal_row):
    dim = rep["dimension"]
    walls = rep["walls"]
    queue = deque([(tuple(position), 0)])
    seen = {tuple(position)}
    while queue:
        (row, col), dist = queue.popleft()
        if row == goal_row:
            return dist
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = row + dr, col + dc
            if 0 <= nr < dim and 0 <= nc < dim and (nr, nc) not in seen:
                if not blocked(walls, (row, col), (nr, nc), dim):
                    seen.add((nr, nc))
                    queue.append(((nr, nc), dist + 1))
    return None


def analyse(path: Path) -> None:
    data = json.loads(path.read_text())
    steps = data["steps"]
    summary = data.get("final_summary", {})
    first = steps[0]
    players = {str(p["id"]): p for p in first["players"]}
    winners = {str(w) for w in summary.get("winners_id", [])}

    print(f"\n{'=' * 78}\n{path.name}   ({len(steps) - 1} plies)")
    for pid, player in players.items():
        mark = "WON " if pid in winners else "lost"
        print(f"  {mark}  {player['name']}  ({player['piece_type']}, goal row {player['goal_row']})")

    # Per-move time, from the drop in remaining_time between consecutive steps.
    moves = {pid: [] for pid in players}
    for before, after in zip(steps, steps[1:]):
        mover = str(before["active_player"]["id"])
        spent = before["remaining_time"][mover] - after["remaining_time"][mover]
        moves[mover].append(spent)

    print(f"\n  {'player':<34} {'moves':>5} {'used':>8} {'left':>8} {'max':>7} {'mean':>7}")
    for pid, player in players.items():
        times = moves[pid]
        left = steps[-1]["remaining_time"][pid]
        print(f"  {player['name'][:33]:<34} {len(times):>5} {900 - left:>7.0f}s {left:>7.0f}s "
              f"{max(times):>6.1f}s {sum(times)/len(times):>6.1f}s")
        over = [t for t in times if t > 30.5]
        if over:
            print(f"      !! {len(over)} move(s) over the 30s cap, worst {max(over):.1f}s"
                  f"  -> this build is NOT the capped one")
        capped = [t for t in times if 29.5 < t <= 30.5]
        if capped:
            share = 100 * sum(capped) / max(900 - left, 1)
            print(f"      {len(capped)} move(s) pinned at the 30s cap "
                  f"= {sum(capped):.0f}s ({share:.0f}% of all time it spent)")

    # First third of the moves vs the rest: where did the budget go?
    for pid, player in players.items():
        times = moves[pid]
        third = max(1, len(times) // 3)
        early, late = sum(times[:third]), sum(times[third:])
        print(f"  {player['name'][:28]:<30} opening {third:>2} moves: {early:>6.0f}s   "
              f"remaining {len(times) - third:>2} moves: {late:>6.0f}s")

    # Did anyone get sealed off? Track each player's true distance over time.
    print()
    for pid, player in players.items():
        goal = player["goal_row"]
        series = []
        for step in steps:
            dist = distance(step["rep"], step["rep"]["pawn_positions"][pid], goal)
            series.append(dist if dist is not None else -1)
        best = min(d for d in series if d >= 0)
        best_at = series.index(best)
        worst_after = max(series[best_at:]) if best_at < len(series) else best
        if worst_after > best + 2:
            print(f"  !! {player['name'][:40]}: was {best} step(s) from winning at ply {best_at}, "
                  f"then fell back to {worst_after} -- sealed off behind walls")
        walls_used = 10 - steps[-1]["rep"]["remaining_walls"][pid]
        print(f"     {player['name'][:40]}: used {walls_used}/10 walls, "
              f"distance went {series[0]} -> min {best} -> {series[-1]}")


if __name__ == "__main__":
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit("give one or more fight_*.json paths")
    for path in paths:
        analyse(path)
