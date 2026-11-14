"""
Local search over the agent's evaluation parameters (hill climbing).

The evaluation of `my_player.py` has one parameter that decides when the
agent spends a wall and when it keeps it:

    W_WALLS    value of one wall in hand, in hundredths of a pawn step

A second one, WALL_FADE (that value fading linearly once the opponent is
fewer than this many steps from its goal, 1 = never), was tuned together with
it and never helped, so it was removed from the agent. It only exists in the
snapshot versions/v5b_final.py; the run logged in results/local_search.csv is
reproduced with
    --agent versions/v5b_final.py --start W_WALLS=124,WALL_FADE=1

This script tunes by first-improvement hill climbing with step halving:

    state        the parameter values, starting from the current ones
    neighbours   one parameter moved one step up or down
    objective    score of a match "neighbour vs current state"; the neighbour
                 replaces the current state if it scores at least --accept
    when no neighbour is accepted, the W_WALLS step is halved; the search
    stops when the step falls under --min-step or --max-matches is reached

The objective is noisy (it is a match), which is why a neighbour must clear
a margin rather than merely score above 50%, and why the final state is then
confirmed against the starting one on fresh openings it was never tuned on.

Games are played directly on the agent's fast board, with no engine in the
loop, at a FIXED DEPTH: a result then depends only on the two parameter
sets and the opening, never on how loaded the machine is, so the whole run
is reproducible from its seed. Each opening (a few random legal plies,
walls included) is played twice with colours swapped, so a lopsided opening
cancels out instead of adding noise.

Every match is appended to tools/results/local_search.csv.

Usage (from Quoridor/):
    python tools/local_search.py --depth 5 --games 80 --workers 12
    python tools/local_search.py match --a W_WALLS=80 --b W_WALLS=124 --games 120

Parallelism here is only across independent games of the tuning run; the
agent itself stays single-threaded, as the rules require.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import multiprocessing
import random
import sys
import time
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))

from actions_quoridor import Orientation, Wall  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "local_search.csv"
FADE_VALUES = (1, 2, 3, 4, 6, 8)   # WALL_FADE moves along this ladder
OPENING_PLIES = 4
OPENING_WALL_PROBABILITY = 0.3
MAX_PLIES = 220                    # longer than any sane game: counted as a draw

_modules: dict[tuple, object] = {}  # per process: parameter set -> loaded agent module


def load_agent_module(agent_path: str, params: dict):
    """A private copy of the agent module with the given constants overridden."""
    key = (agent_path,) + tuple(sorted(params.items()))
    module = _modules.get(key)
    if module is None:
        path = (QUORIDOR_DIR / agent_path).resolve()
        spec = importlib.util.spec_from_file_location(f"ls_agent_{len(_modules)}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for name, value in params.items():
            if not hasattr(module, name):
                raise SystemExit(f"{agent_path} has no constant {name}")
            setattr(module, name, value)
        _modules[key] = module
    return module


class _Seat:
    """Minimal stand-in for an engine player, for building boards."""

    def __init__(self, player_id: int, goal_row: int) -> None:
        self.id = player_id
        self.goal_row = goal_row

    def get_goal_row(self) -> int:
        return self.goal_row


class _Rep:
    def __init__(self, dimension: int, pawn_positions: dict, remaining_walls: dict) -> None:
        self.dimension = dimension
        self.pawn_positions = pawn_positions
        self.remaining_walls = remaining_walls
        self.walls: set[Wall] = set()


class _Position:
    """
    Just enough of GameStateQuoridor for the agent's `_Board` and
    `_record_position`: the tuning games never touch the real engine, whose
    legal-action enumeration alone costs more than a shallow search.
    """

    def __init__(self, white_id: int, black_id: int, dimension: int = 9, walls: int = 10) -> None:
        self.players = [_Seat(white_id, 0), _Seat(black_id, dimension - 1)]
        middle = dimension // 2
        self.rep = _Rep(dimension,
                        {white_id: (dimension - 1, middle), black_id: (0, middle)},
                        {white_id: walls, black_id: walls})
        self.active_player = self.players[0]
        self.step = 0

    def get_step(self) -> int:
        return self.step

    def play(self, move: int) -> bool:
        """Apply a move in the agent's int encoding; True if it wins the game."""
        dim = self.rep.dimension
        size = dim * dim
        mover = self.active_player
        won = False
        if move < size:
            self.rep.pawn_positions[mover.id] = divmod(move, dim)
            won = move // dim == mover.goal_row
        else:
            row, col = divmod(move % size, dim)
            orientation = Orientation.HORIZONTAL if move < 2 * size else Orientation.VERTICAL
            self.rep.walls.add(Wall(row, col, orientation))
            self.rep.remaining_walls[mover.id] -= 1
        self.active_player = self.players[1] if mover is self.players[0] else self.players[0]
        self.step += 1
        return won


def play_game(task: tuple) -> float:
    """One game. Returns A's score: 1 win, 0.5 draw, 0 loss."""
    agent_path, params_a, params_b, opening_seed, a_is_white, depth = task
    module_a = load_agent_module(agent_path, params_a)
    module_b = load_agent_module(agent_path, params_b)
    white_module, black_module = (module_a, module_b) if a_is_white else (module_b, module_a)
    white = white_module.MyPlayer("W", goal_row=0, name="white")
    black = black_module.MyPlayer("B", goal_row=8, name="black")
    position = _Position(white.id, black.id)
    seats = {white.id: (white, white_module), black.id: (black, black_module)}

    # Random opening, identical for both colour assignments of this seed.
    rng = random.Random(opening_seed)
    for _ in range(OPENING_PLIES):
        mover_id = position.active_player.id
        board = module_a._Board(position, mover_id)
        moves = board.pawn_destinations(0)
        if rng.random() < OPENING_WALL_PROBABILITY:
            walls = [code for code in range(board.size, 3 * board.size) if board.wall_legal(code)]
            if walls:
                moves = walls
        position.play(rng.choice(moves))

    while position.step < MAX_PLIES:
        mover_id = position.active_player.id
        agent, module = seats[mover_id]
        agent._record_position(position)
        board = module._Board(position, mover_id)
        moves = agent._root_moves(board)
        if not moves:
            return 0.5
        move = moves[0] if len(moves) == 1 else agent._search(
            board, moves, time.perf_counter(), 1e9, max_depth=depth)
        if position.play(move):
            a_won = (mover_id == white.id) == a_is_white
            return 1.0 if a_won else 0.0
    return 0.5


class Tuner:
    def __init__(self, args) -> None:
        self.args = args
        self.pool = multiprocessing.Pool(args.workers)
        self.next_seed = args.seed * 1_000_000
        self.matches = 0

    def match(self, params_a: dict, params_b: dict, games: int, label: str) -> float:
        """Score of A against B over `games` games (paired openings, fresh every match)."""
        tasks = []
        for pair in range(games // 2):
            seed = self.next_seed + pair
            tasks.append((self.args.agent, params_a, params_b, seed, True, self.args.depth))
            tasks.append((self.args.agent, params_a, params_b, seed, False, self.args.depth))
        self.next_seed += games
        start = time.perf_counter()
        score = sum(self.pool.imap_unordered(play_game, tasks, chunksize=1))
        self.matches += 1
        rate = score / len(tasks)
        margin = 2 * (max(rate * (1 - rate), 0.01) / len(tasks)) ** 0.5
        print(f"  {label}: {fmt(params_a)} vs {fmt(params_b)} -> {score:g}/{len(tasks)} "
              f"= {100 * rate:.1f}% (+-{100 * margin:.0f})  [{time.perf_counter() - start:.0f}s]", flush=True)
        self.log(label, params_a, params_b, len(tasks), score)
        return rate

    def log(self, label: str, params_a: dict, params_b: dict, games: int, score: float) -> None:
        RESULTS_PATH.parent.mkdir(exist_ok=True)
        new_file = not RESULTS_PATH.exists()
        with RESULTS_PATH.open("a", newline="") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(["run_seed", "depth", "label", "a", "b", "games", "score_a", "rate_a"])
            writer.writerow([self.args.seed, self.args.depth, label, fmt(params_a), fmt(params_b),
                             games, score, round(score / games, 4)])

    def neighbours(self, state: dict, wall_step: int) -> list[dict]:
        out = []
        for delta in (-wall_step, wall_step):
            value = state["W_WALLS"] + delta
            if value >= 0:
                out.append({**state, "W_WALLS": value})
        if "WALL_FADE" in state:  # only for agent files that still have it
            index = FADE_VALUES.index(state["WALL_FADE"])
            for other in (index + 1, index - 1):
                if 0 <= other < len(FADE_VALUES):
                    out.append({**state, "WALL_FADE": FADE_VALUES[other]})
        return out

    def climb(self, start: dict) -> dict:
        args = self.args
        current = dict(start)
        wall_step = args.step
        rejected: set[tuple] = set()   # (neighbour, state it lost to)
        print(f"start {fmt(current)}; depth {args.depth}, {args.games} games per match, "
              f"accept at {100 * args.accept:.1f}%")
        while wall_step >= args.min_step and self.matches < args.max_matches:
            improved = False
            for candidate in self.neighbours(current, wall_step):
                key = (fmt(candidate), fmt(current))
                if key in rejected or (fmt(current), fmt(candidate)) in rejected:
                    continue  # already compared, or the state we just climbed away from
                if self.matches >= args.max_matches:
                    break
                rate = self.match(candidate, current, args.games, "climb")
                if rate >= args.accept:
                    rejected.add((fmt(current), fmt(candidate)))
                    current = candidate
                    improved = True
                    print(f"  -> accepted, now at {fmt(current)}", flush=True)
                    break
                rejected.add(key)
            if not improved:
                wall_step //= 2
                print(f"  no neighbour accepted; W_WALLS step -> {wall_step}", flush=True)
        return current


def fmt(params: dict) -> str:
    return " ".join(f"{name}={value}" for name, value in sorted(params.items()))


def parse_params(text: str) -> dict:
    return {name: int(value) for name, value in (item.split("=") for item in text.split(","))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", nargs="?", default="climb", choices=["climb", "match"])
    parser.add_argument("--agent", default="my_player.py")
    parser.add_argument("--start", default="W_WALLS=124")
    parser.add_argument("--a", default=None, help="match mode: parameters of A")
    parser.add_argument("--b", default=None, help="match mode: parameters of B")
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--games", type=int, default=80)
    parser.add_argument("--accept", type=float, default=0.575)
    parser.add_argument("--step", type=int, default=40)
    parser.add_argument("--min-step", type=int, default=10)
    parser.add_argument("--max-matches", type=int, default=16)
    parser.add_argument("--confirm-games", type=int, default=160)
    parser.add_argument("--workers", type=int, default=max(1, multiprocessing.cpu_count() // 2))
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    tuner = Tuner(args)
    start = parse_params(args.start)
    if args.mode == "match":
        tuner.match({**start, **parse_params(args.a)}, {**start, **parse_params(args.b)},
                    args.games, "match")
        return

    best = tuner.climb(start)
    print(f"\nlocal optimum: {fmt(best)}")
    if fmt(best) != fmt(start) and args.confirm_games:
        print("confirmation against the starting point, on openings not used above:")
        tuner.match(best, start, args.confirm_games, "confirm")


if __name__ == "__main__":
    main()
