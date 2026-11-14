"""Figures of the report (static, print, light surface). Run with the conda Python (matplotlib)."""
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

HERE = Path(__file__).parent
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#ffffff"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"

plt.rcParams.update({
    "font.family": "Segoe UI", "font.size": 10, "text.color": INK,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.linewidth": 0.8,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 10, "ytick.labelsize": 10,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def fr(value: float) -> str:
    """French number formatting: thin space for thousands."""
    return f"{value:,.0f}".replace(",", " ")


def geomean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


def fig_pruning():
    rows = json.loads((HERE / "ablation.json").read_text())
    series = [
        ("minimax", "Minimax sans élagage", MUTED, lambda r: r["minimax"]),
        ("table", "Alpha-bêta à variation principale + table de transposition", ORANGE,
         lambda r: r["table"]["nodes"]),
        ("full", "+ réductions des coups tardifs (agent final)", BLUE, lambda r: r["full"]["nodes"]),
    ]
    fig, ax = plt.subplots(figsize=(6.7, 3.0), dpi=300)
    summary = {}
    for key, label, colour, getter in series:
        depth_count = min(len(getter(r)) for r in rows)
        means = [geomean([max(1, getter(r)[d]) for r in rows]) for d in range(depth_count)]
        summary[key] = means
        xs = list(range(1, depth_count + 1))
        ax.plot(xs, means, color=colour, linewidth=2, solid_capstyle="round",
                solid_joinstyle="round", label=label, zorder=3)
        ax.plot(xs[-1], means[-1], "o", color=colour, markersize=7,
                markeredgecolor=SURFACE, markeredgewidth=1.6, zorder=4)
        offset, align = ((-2, 9), "right") if key == "table" else ((7, 0), "left")
        ax.annotate(fr(means[-1]), (xs[-1], means[-1]), xytext=offset, textcoords="offset points",
                    va="center", ha=align, color=INK, fontsize=10)
    ax.set_yscale("log")
    ax.set_xlim(0.8, 8.9)
    ax.set_ylim(8, 4_000_000)
    ax.yaxis.set_major_locator(FixedLocator([10, 100, 1_000, 10_000, 100_000, 1_000_000]))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fr(v)))
    ax.set_xticks(range(1, 9))
    ax.set_xlabel("Profondeur terminée (demi-coups)")
    ax.set_ylabel("Positions visitées (échelle log)")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.legend(loc="upper left", frameon=False, fontsize=10, handlelength=1.6,
              labelcolor=INK2, borderaxespad=0.2)
    fig.tight_layout(pad=0.4)
    fig.savefig(HERE / "fig_pruning.png")
    plt.close(fig)
    return summary, len(rows)


def wilson(wins: float, games: int, z: float = 1.96):
    p = wins / games
    centre = (p + z * z / (2 * games)) / (1 + z * z / games)
    half = z * math.sqrt(p * (1 - p) / games + z * z / (4 * games * games)) / (1 + z * z / games)
    return max(0.0, centre - half), min(1.0, centre + half)


ROW = 0.215


def fig_matches(groups):
    """groups: list of (heading, [(label, points, games), ...]); points = wins + draws / 2."""
    count = sum(len(items) for _, items in groups) + len(groups)
    fig, ax = plt.subplots(figsize=(6.7, ROW * count + 0.62), dpi=300)
    y = 0
    ticks, labels = [], []
    for heading, items in groups:
        ax.text(-0.02, y, heading, transform=ax.get_yaxis_transform(), ha="right", va="center",
                fontsize=10, fontweight="bold", color=INK)
        y += 1
        for label, points, games in items:
            low, high = wilson(points, games)
            rate = points / games
            ax.plot([low * 100, high * 100], [y, y], color=BLUE, linewidth=2,
                    solid_capstyle="round", alpha=0.45, zorder=2)
            ax.plot(rate * 100, y, "o", color=BLUE, markersize=7.5, clip_on=False,
                    markeredgecolor=SURFACE, markeredgewidth=1.6, zorder=3)
            score = f"{points:g}".replace(".", ",")
            ax.text(104, y, f"{rate * 100:.0f} %  ({score}/{games})", va="center", ha="left",
                    fontsize=10, color=INK)
            ticks.append(y)
            labels.append(label)
            y += 1
    ax.axvline(50, color=AXIS, linewidth=1, zorder=1)
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels, color=INK2)
    ax.set_ylim(y - 0.4, -0.6)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f} %"))
    ax.set_xlabel("Score de la variante testée (point = score observé, trait = intervalle à 95 %)")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    fig.subplots_adjust(left=0.36, right=0.83, top=0.99, bottom=0.46 / (ROW * count + 0.62))
    fig.savefig(HERE / "fig_matches.png")
    plt.close(fig)


if __name__ == "__main__":
    summary, positions = fig_pruning()
    print("positions:", positions)
    for key, means in summary.items():
        print(key, [round(m) for m in means])
    groups = json.loads((HERE / "matches.json").read_text(encoding="utf-8"))
    fig_matches([(g["heading"], [tuple(i) for i in g["items"]]) for g in groups])
    for g in groups:
        for label, points, games in g["items"]:
            low, high = wilson(points, games)
            print(f"{label:45s} {points}/{games} = {points / games:.0%}  [{low:.0%}, {high:.0%}]")
