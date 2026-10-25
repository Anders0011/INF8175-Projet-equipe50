"""
Do two agent versions actually play differently?

Win rate is a very noisy way to answer this: a 16-game match has a ~+-24
point margin, so a change worth a few points is invisible. This asks the
cheaper, sharper question first -- on the same positions, how often do the
two versions choose a different action?

A change that never alters a decision cannot alter a result, however good
the idea behind it looks. Only run a long match for changes that get past
this.

Usage (from Quoridor/, venv activated):
    python tools/behaviour_diff.py my_player.py versions/v3_fastboard.py --positions 60 --time 5
"""
from __future__ import annotations

import argparse
import importlib.util
import random
import sys
from pathlib import Path

QUORIDOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUORIDOR_DIR))

from board_quoridor import BoardQuoridor  # noqa: E402
from game_state_quoridor import GameStateQuoridor  # noqa: E402


def load_agent_class(path: str):
    file_path = (QUORIDOR_DIR / path).resolve()
    spec = importlib.util.spec_from_file_location(f"bd_{file_path.stem}_{abs(hash(path))}", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MyPlayer


def sample_positions(count: int, seed: int, wall_bias: float = 0.35):
    """Positions from semi-random play, so walls accumulate like in a real game."""
    rng = random.Random(seed)
    out = []
    while len(out) < count:
        p1 = _Dummy("W", 0)
        p2 = _Dummy("B", 8)
        board = BoardQuoridor({p1.id: (8, 4), p2.id: (0, 4)}, frozenset(), {p1.id: 10, p2.id: 10})
        state = GameStateQuoridor({p1.id: 0, p2.id: 0}, p1, [p1, p2], board, step=0)
        while not state.is_done() and state.step < 70 and len(out) < count:
            actions = list(state.generate_possible_stateless_actions())
            moves = [a for a in actions if a.data["type"] == "move"]
            walls = [a for a in actions if a.data["type"] != "move"]
            pool = walls if (walls and rng.random() < wall_bias) else moves
            state = state.apply_action(rng.choice(pool or actions))
            if state.step % 2 == 0:
                out.append(state)
    return out


class _Dummy:
    """Minimal stand-in used only to build positions."""
    _next = 1

    def __init__(self, piece_type, goal_row):
        self.piece_type = piece_type
        self.goal_row = goal_row
        self.id = _Dummy._next
        _Dummy._next += 1

    def get_goal_row(self):
        return self.goal_row

    def get_id(self):
        return self.id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent_a")
    parser.add_argument("agent_b")
    parser.add_argument("--positions", type=int, default=50)
    parser.add_argument("--time", type=float, default=5.0, help="remaining_time handed to each agent")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    cls_a, cls_b = load_agent_class(args.agent_a), load_agent_class(args.agent_b)
    name_a, name_b = Path(args.agent_a).stem, Path(args.agent_b).stem

    differences = 0
    tested = 0
    examples = []

    for state in sample_positions(args.positions, args.seed):
        active = state.active_player
        picks = []
        for cls in (cls_a, cls_b):
            agent = cls(active.get_piece_type() if hasattr(active, "get_piece_type") else "W",
                        goal_row=active.get_goal_row(), name="x")
            agent.id = active.get_id()
            agent.goal_row = active.get_goal_row()
            picks.append(agent.compute_action(state, remaining_time=args.time).data)

        tested += 1
        if picks[0] != picks[1]:
            differences += 1
            if len(examples) < 5:
                examples.append((state.step, picks[0], picks[1]))

    pct = 100 * differences / tested if tested else 0
    print(f"\npositions compared: {tested}")
    print(f"different choice:   {differences} ({pct:.0f}%)")
    if differences == 0:
        print(f"\n{name_a} and {name_b} are BEHAVIOURALLY IDENTICAL on these positions.")
        print("A change that never alters a decision cannot alter a result -- skip the match.")
    else:
        print(f"\nexamples ({name_a} vs {name_b}):")
        for step, a, b in examples:
            print(f"  step {step:>3}: {a}   vs   {b}")


if __name__ == "__main__":
    main()
