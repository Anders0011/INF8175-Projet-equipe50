"""
Fit the evaluation weights to real game outcomes (Texel-style tuning).

Why: judging an evaluation change by win rate needs ~30 minutes per idea and
still leaves a +-17 point margin, so every realistic improvement hides in the
noise. A single 60-ply game instead yields ~60 labelled positions ("did the
side to move eventually win?"), which is a ~60x jump in data efficiency.

Two phases:
  collect  self-play games, recording features + the eventual winner
  fit      logistic regression  P(win) = sigmoid(w . x)  by gradient descent

The fit is also a DIAGNOSTIC, and that is its first value: a feature whose
coefficient lands near zero carries no information about winning, whatever it
looks like on paper. If `lead` alone predicts as well as everything else, the
evaluation is already at its information ceiling and no reweighting will help.

Training happens here, offline. Only the resulting numbers go into
my_player.py, so the agent ships with no new dependency.

Usage (from Quoridor/, venv activated):
    python tools/tune_weights.py collect --games 40 --time 6
    python tools/tune_weights.py fit
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))

from board_quoridor import BoardQuoridor  # noqa: E402
from game_state_quoridor import GameStateQuoridor  # noqa: E402

DATA_PATH = Path(__file__).resolve().parent / "results" / "tuning_data.jsonl"

# Deliberately NOT included:
#   "lead" (= opp_distance - my_distance) is a linear combination of the two
#   distance features, which makes the design matrix rank-deficient and the
#   coefficients individually meaningless. Keeping the distances separate spans
#   the same space AND lets a non-linear distance response be learned; if the
#   two come back symmetric, the current lead-based form is validated.
#   "to_move" is constant here: positions are recorded from the point of view
#   of the player about to move, so it carries no variance.
FEATURES = [
    "my_distance",
    "opp_distance",
    "min_distance",    # how close the nearer pawn is to finishing (urgency)
    "walls_diff",
    "mobility_diff",
    "routes_diff",     # log1p(my shortest-path count) - log1p(opponent's)
]


def load_agent(path: str):
    file_path = (QUORIDOR_DIR / path).resolve()
    spec = importlib.util.spec_from_file_location(f"tw_{file_path.stem}", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def count_routes(board, player: int) -> int:
    """Number of distinct shortest paths to the goal; layer-by-layer BFS."""
    start = board.pawns[player]
    goal_row = board.goals[player]
    row_of = board.geo.row_of
    if row_of[start] == goal_row:
        return 1
    neighbours, blocked = board.geo.neighbours, board.blocked
    size = board.dim * board.dim
    dist, routes = [-1] * size, [0] * size
    dist[start], routes[start] = 0, 1
    frontier, depth = [start], 0
    while frontier:
        reached = [c for c in frontier if row_of[c] == goal_row]
        if reached:
            return min(100_000, sum(routes[c] for c in reached))
        nxt, depth = [], depth + 1
        for cell in frontier:
            mask, row, count = blocked[cell], neighbours[cell], routes[cell]
            for direction in range(4):
                if mask & (1 << direction):
                    continue
                target = row[direction]
                if target < 0:
                    continue
                if dist[target] == -1:
                    dist[target], routes[target] = depth, count
                    nxt.append(target)
                elif dist[target] == depth:
                    routes[target] = min(100_000, routes[target] + count)
        frontier = nxt
    return 0


def extract(board) -> list[float] | None:
    """Features from player 0's point of view."""
    my_distance = board.distance(0)
    opp_distance = board.distance(1)
    if my_distance is None or opp_distance is None:
        return None
    return [
        float(my_distance),
        float(opp_distance),
        float(min(my_distance, opp_distance)),
        float(board.walls_left[0] - board.walls_left[1]),
        float(board.mobility(0) - board.mobility(1)),
        math.log1p(count_routes(board, 0)) - math.log1p(count_routes(board, 1)),
    ]


def collect(args) -> None:
    agents = [load_agent(p) for p in args.agents]
    rng = random.Random(args.seed)
    DATA_PATH.parent.mkdir(exist_ok=True)
    written = 0

    with DATA_PATH.open("a") as handle:
        for game in range(args.games):
            # Mix opponents so the weights do not overfit one playing style.
            mod_w, mod_b = rng.choice(agents), rng.choice(agents)
            white = mod_w.MyPlayer("W", goal_row=0, name="w")
            black = mod_b.MyPlayer("B", goal_row=8, name="b")
            players = {white.id: white, black.id: black}

            rep = BoardQuoridor({white.id: (8, 4), black.id: (0, 4)},
                                frozenset(), {white.id: 10, black.id: 10})
            state = GameStateQuoridor({white.id: 0, black.id: 0}, white,
                                      [white, black], rep, step=0)
            remaining = {white.id: args.time, black.id: args.time}

            samples = []
            for ply in range(args.max_steps):
                if state.is_done():
                    break
                active = state.active_player.id
                if ply < args.random_plies:
                    moves = [a for a in state.generate_possible_stateless_actions()
                             if a.data["type"] == "move"]
                    action = rng.choice(moves)
                else:
                    action = players[active].compute_action(state, remaining_time=remaining[active])
                # Record from the point of view of the player about to move.
                board = agents[0]._Board(state, active)
                row = extract(board)
                if row is not None:
                    samples.append((active, row))
                state = state.apply_action(action)

            winner = next((pid for pid, score in state.scores.items() if score == 1.0), None)
            if winner is None:
                continue
            for owner, row in samples:
                handle.write(json.dumps({"x": row, "y": 1 if owner == winner else 0}) + "\n")
                written += 1
            handle.flush()
            print(f"game {game + 1}/{args.games}: {len(samples)} positions, "
                  f"winner {'W' if winner == white.id else 'B'}")

    print(f"\nwrote {written} labelled positions to {DATA_PATH}")


def fit(args) -> None:
    rows = [json.loads(line) for line in DATA_PATH.read_text().splitlines() if line.strip()]
    if not rows:
        sys.exit("no data; run `collect` first")

    X = np.array([r["x"] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)

    # Hold out a validation split: training accuracy alone is optimistic, and
    # late-game positions are trivially predictable.
    generator = np.random.default_rng(0)
    shuffled = generator.permutation(len(y))
    split = int(0.8 * len(y))
    train, validate = shuffled[:split], shuffled[split:]

    mean, std = X[train].mean(axis=0), X[train].std(axis=0)
    std[std == 0] = 1.0
    Z = (X - mean) / std

    weights = np.zeros(Z.shape[1])
    bias = 0.0
    for _ in range(args.steps):
        prediction = 1.0 / (1.0 + np.exp(-(Z[train] @ weights + bias)))
        error = prediction - y[train]
        weights -= args.lr * (Z[train].T @ error / len(train) + args.l2 * weights)
        bias -= args.lr * error.mean()

    def accuracy_on(indices):
        prediction = 1.0 / (1.0 + np.exp(-(Z[indices] @ weights + bias)))
        return ((prediction > 0.5) == (y[indices] > 0.5)).mean()

    baseline = max(y.mean(), 1 - y.mean())
    print(f"positions: {len(y)}  (train {len(train)} / validate {len(validate)})")
    print(f"accuracy: train {accuracy_on(train):.3f}   validate {accuracy_on(validate):.3f}"
          f"   (always-guess-majority: {baseline:.3f})\n")

    per_unit = weights / std
    ranking = np.argsort(-np.abs(weights))
    print(f"{'feature':>14} {'standardised':>13} {'per unit':>10}")
    for index in ranking:
        print(f"{FEATURES[index]:>14} {weights[index]:>13.3f} {per_unit[index]:>10.3f}")

    # Anchor so the distance response matches today's W_DISTANCE, making the
    # other numbers directly comparable to the weights now in my_player.py.
    my_index, opp_index = FEATURES.index("my_distance"), FEATURES.index("opp_distance")
    anchor = (abs(per_unit[my_index]) + abs(per_unit[opp_index])) / 2
    if anchor > 1e-9:
        scale = 25.0 / anchor
        print("\nimplied weights, scaled so the distance response equals W_DISTANCE = 25:")
        for index in ranking:
            print(f"{FEATURES[index]:>14} {per_unit[index] * scale:>10.2f}")
        print("\nmy_distance and opp_distance should come out near-symmetric (-25 / +25) if the")
        print("current lead-based form is right. A coefficient near zero carries no information.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--games", type=int, default=40)
    c.add_argument("--time", type=float, default=6.0)
    c.add_argument("--random-plies", type=int, default=4)
    c.add_argument("--max-steps", type=int, default=140)
    c.add_argument("--seed", type=int, default=0)
    # Self-play by default, ON PURPOSE. Mixing agents of unequal strength
    # poisons the labels: if one agent wins more, every feature that merely
    # reflects its style gets credited for winning, and the fit learns "which
    # agent is this" instead of "is this position good". Diversity comes from
    # --random-plies instead. Pass --agents only to study style differences.
    c.add_argument("--agents", nargs="*", default=["my_player.py"])
    c.set_defaults(func=collect)

    f = sub.add_parser("fit")
    f.add_argument("--steps", type=int, default=4000)
    f.add_argument("--lr", type=float, default=0.5)
    f.add_argument("--l2", type=float, default=1e-4)
    f.set_defaults(func=fit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
