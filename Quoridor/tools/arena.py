"""
Arena: plays many games between two agents in-process and reports win rates.

Usage (from the Quoridor/ folder, venv activated):
    python tools/arena.py my_player.py versions/v1_minimax.py --games 10 --time 120 --random-plies 2

Colors alternate every game. Results are appended to tools/results/<a>_vs_<b>.csv.
Faster than main_quoridor.py (no subprocess/network layer), but slightly
optimistic on timing: IPC latency of the real harness is not counted.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import random
import sys
import time
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))

from board_quoridor import BoardQuoridor  # noqa: E402
from game_state_quoridor import GameStateQuoridor  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_agent_class(path: str):
    file_path = (QUORIDOR_DIR / path).resolve() if not Path(path).is_absolute() else Path(path)
    module_name = f"arena_{file_path.stem}_{abs(hash(str(file_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MyPlayer


def play_game(white_cls, black_cls, time_budget: float, random_plies: int, max_steps: int, rng: random.Random) -> dict:
    white = white_cls("W", goal_row=0, name="white")
    black = black_cls("B", goal_row=8, name="black")
    players = {white.id: white, black.id: black}

    board = BoardQuoridor({white.id: (8, 4), black.id: (0, 4)}, frozenset(), {white.id: 10, black.id: 10})
    state = GameStateQuoridor({white.id: 0, black.id: 0}, white, [white, black], board, step=0)

    remaining = {white.id: time_budget, black.id: time_budget}
    max_move_time = {white.id: 0.0, black.id: 0.0}
    # CPU time of the slowest move: if it is far below the wall-clock time of
    # that same move, the process was suspended (machine sleep), not slow.
    max_move_cpu = {white.id: 0.0, black.id: 0.0}
    winner, reason = None, "goal"

    while not state.is_done():
        if state.step >= max_steps:
            reason = "max_steps"
            break

        active_id = state.active_player.id
        legal = tuple(state.generate_possible_stateless_actions())

        if state.step < random_plies:
            moves = [a for a in legal if a.data["type"] == "move"]
            action = rng.choice(moves or list(legal))
        else:
            start, start_cpu = time.perf_counter(), time.process_time()
            try:
                action = players[active_id].compute_action(state, remaining_time=remaining[active_id])
            except Exception as exc:  # a crash loses the game, like on Abyss
                winner, reason = _other(players, active_id), f"crash:{type(exc).__name__}"
                break
            elapsed = time.perf_counter() - start
            elapsed_cpu = time.process_time() - start_cpu
            remaining[active_id] -= elapsed
            if elapsed > max_move_time[active_id]:
                max_move_time[active_id] = elapsed
                max_move_cpu[active_id] = elapsed_cpu

            if remaining[active_id] < 0:
                winner, reason = _other(players, active_id), "timeout"
                break
            if not any(a.data == action.data for a in legal):
                winner, reason = _other(players, active_id), "illegal"
                break

        state = state.apply_action(action)

    if winner is None and state.is_done():
        winner = next(pid for pid, score in state.scores.items() if score == 1.0)

    return {
        "winner": "white" if winner == white.id else "black" if winner == black.id else "draw",
        "reason": reason,
        "steps": state.step,
        "white_time_used": round(time_budget - remaining[white.id], 2),
        "black_time_used": round(time_budget - remaining[black.id], 2),
        "white_max_move": round(max_move_time[white.id], 2),
        "black_max_move": round(max_move_time[black.id], 2),
        "white_max_move_cpu": round(max_move_cpu[white.id], 2),
        "black_max_move_cpu": round(max_move_cpu[black.id], 2),
        "white_walls_left": state.rep.remaining_walls[white.id],
        "black_walls_left": state.rep.remaining_walls[black.id],
    }


def _other(players: dict, player_id: int) -> int:
    return next(pid for pid in players if pid != player_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent_a")
    parser.add_argument("agent_b")
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--time", type=float, default=15 * 60, help="time budget per agent per game (s)")
    parser.add_argument("--random-plies", type=int, default=0,
                        help="random pawn moves at the start of each game, for variety between games "
                             "(use an EVEN number so both colors get the same handicap)")
    parser.add_argument("--max-steps", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.random_plies % 2:
        # White would get one more random (often bad) opening move than Black.
        print(f"warning: --random-plies {args.random_plies} is odd, so the colors get unequal "
              f"random openings; use {args.random_plies + 1} for a fair comparison.")

    cls_a, cls_b = load_agent_class(args.agent_a), load_agent_class(args.agent_b)
    name_a, name_b = Path(args.agent_a).stem, Path(args.agent_b).stem
    rng = random.Random(args.seed)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{name_a}_vs_{name_b}.csv"
    write_header = not out_path.exists()

    wins = {name_a: 0, name_b: 0, "draw": 0}
    with out_path.open("a", newline="") as f:
        writer = None
        for game in range(args.games):
            a_is_white = game % 2 == 0
            white_cls, black_cls = (cls_a, cls_b) if a_is_white else (cls_b, cls_a)
            white_name, black_name = (name_a, name_b) if a_is_white else (name_b, name_a)

            # Paired openings: the two games of a pair share one random opening
            # and swap colors, so opening luck cancels instead of adding noise.
            rng = random.Random(args.seed * 1000 + game // 2)

            result = play_game(white_cls, black_cls, args.time, args.random_plies, args.max_steps, rng)
            winner_name = {"white": white_name, "black": black_name, "draw": "draw"}[result["winner"]]
            wins[winner_name] += 1

            row = {"game": game, "white": white_name, "black": black_name, "winner_name": winner_name,
                   "time_budget": args.time, "random_plies": args.random_plies, **result}
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row))
                if write_header:
                    writer.writeheader()
            writer.writerow(row)
            f.flush()

            print(f"game {game + 1}/{args.games}: {white_name}(W) vs {black_name}(B) -> {winner_name} "
                  f"[{result['reason']}, {result['steps']} steps, time W={result['white_time_used']}s "
                  f"B={result['black_time_used']}s]")

    total = args.games
    rate = wins[name_a] / total
    # Standard error of a win rate; ~2x this is the 95% margin. Printed because
    # a 16-game match has a +-24 point margin, wide enough to hide any realistic
    # improvement -- treat a result as real only if it clears the margin.
    stderr = (rate * (1 - rate) / total) ** 0.5
    print(f"\n{name_a}: {wins[name_a]}/{total} ({100 * rate:.0f}%)  "
          f"{name_b}: {wins[name_b]}/{total} ({100 * wins[name_b] / total:.0f}%)  draws: {wins['draw']}")
    print(f"95% margin: +-{200 * stderr:.0f} points  "
          f"-> {name_a} true win rate is somewhere in "
          f"[{max(0, 100 * rate - 200 * stderr):.0f}%, {min(100, 100 * rate + 200 * stderr):.0f}%]")
    if 100 * rate - 200 * stderr < 50 < 100 * rate + 200 * stderr:
        print("VERDICT: not distinguishable from an even match -- need more games.")
    print(f"results appended to {out_path}")


if __name__ == "__main__":
    main()
