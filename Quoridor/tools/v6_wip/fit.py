"""What is a wall worth on Abyss? Wall returns by context, then logistic fits of the game outcome."""
import collections
import pickle
import random
import sys

import numpy as np

games = pickle.load(open(sys.argv[1], "rb"))
print(len(games), "games")

# ---------- A. net steps gained per wall placed, by context ----------
by_board = collections.defaultdict(list)
by_victim = collections.defaultdict(list)
by_index = collections.defaultdict(list)
for g in games:
    p = g["plies"]
    for i in range(len(p) - 1):
        mover, d0, d1, w0, w1 = p[i]
        _, e0, e1, x0, x1 = p[i + 1]
        d, e, w, x = (d0, d1), (e0, e1), (w0, w1), (x0, x1)
        if x[mover] != w[mover] - 1:
            continue
        gain = (e[1 - mover] - d[1 - mover]) - (e[mover] - d[mover])
        on_board = 20 - w0 - w1
        by_board[min(on_board // 4, 4)].append(gain)
        by_victim["victim has 0 walls" if w[1 - mover] == 0 else "victim has walls"].append(gain)
        by_index[10 - w[mover] + 1].append(gain)
print("\nA. net steps gained by one wall")
for k in sorted(by_board):
    v = by_board[k]
    print(f"   walls already on board {4*k:2d}-{4*k+3 if k < 4 else 19:2d}: {np.mean(v):+.2f}  (n={len(v)})")
for k, v in sorted(by_victim.items()):
    print(f"   {k}: {np.mean(v):+.2f}  (n={len(v)})")
print("   by the placer's wall number:", "  ".join(f"#{k} {np.mean(v):+.1f}" for k, v in sorted(by_index.items())))

# ---------- B. logistic regression of the outcome ----------
record = collections.defaultdict(lambda: [0, 0])
for g in games:
    for side in (0, 1):
        record[g["tags"][side]][0] += g["winner"] == side
        record[g["tags"][side]][1] += 1
strength = {t: np.log((w + 2.5) / (n - w + 2.5)) for t, (w, n) in record.items()}

rows = []
for gi, g in enumerate(games):
    s = (strength[g["tags"][0]], strength[g["tags"][1]])
    for mover, d0, d1, w0, w1 in g["plies"][4:]:
        d, w = (d0, d1), (w0, w1)
        me, op = mover, 1 - mover
        if d[me] == 0 or d[op] == 0:
            continue
        rows.append((gi, d[op] - d[me], w[me], w[op], s[me] - s[op], 1.0 if g["winner"] == me else 0.0, d[me], d[op]))
rows = np.array(rows)
gid, dd, wm, wo, sd, y, dme, dop = rows.T
print(f"\nB. {len(y)} positions, mover wins {y.mean():.3f}")


def fit(X, y, l2=1e-3, iters=40):
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ beta))
        grad = X.T @ (p - y) + l2 * beta
        hess = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.eye(X.shape[1])
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.abs(step).max() < 1e-8:
            break
    return beta


rng = random.Random(1)
game_ids = sorted(set(gid.astype(int)))
rng.shuffle(game_ids)
test_games = set(game_ids[: len(game_ids) // 5])
test = np.array([int(g) in test_games for g in gid])
train = ~test


def report(name, feats, labels):
    X = np.column_stack(feats + [np.ones_like(y)])
    beta = fit(X[train], y[train])
    p = 1 / (1 + np.exp(-X[test] @ beta))
    acc = ((p > 0.5) == (y[test] > 0.5)).mean()
    ll = -np.mean(y[test] * np.log(p + 1e-12) + (1 - y[test]) * np.log(1 - p + 1e-12))
    beta_all = fit(X, y)
    unit = beta_all[0]
    print(f"\n   {name}: held-out accuracy {acc:.3f}, log-loss {ll:.4f}")
    print("      in steps: " + ", ".join(f"{l} {b / unit:+.2f}" for l, b in zip(labels + ["tempo"], beta_all)))
    return beta_all / unit


zero = (wm == 0).astype(float) - (wo == 0).astype(float)
b0 = report("linear, no skill control", [dd, wm - wo], ["dist", "wall"])
b1 = report("linear + skill", [dd, wm - wo, sd], ["dist", "wall", "skill"])
b2 = report("quadratic stash + skill", [dd, wm - wo, wm**2 - wo**2, sd], ["dist", "wall", "wall^2", "skill"])
b3 = report("quadratic + out-of-walls + skill", [dd, wm - wo, wm**2 - wo**2, zero, sd], ["dist", "wall", "wall^2", "zero", "skill"])
b4 = report("linear + out-of-walls + skill", [dd, wm - wo, zero, sd], ["dist", "wall", "zero", "skill"])

# wall value by game phase (walls still in hand, both sides)
print("\n   wall value by phase (linear + skill), in steps:")
total = wm + wo
for lo, hi in ((16, 20), (11, 15), (6, 10), (1, 5)):
    m = (total >= lo) & (total <= hi)
    X = np.column_stack([dd[m], (wm - wo)[m], sd[m], np.ones(m.sum())])
    beta = fit(X, y[m])
    print(f"      {lo:2d}-{hi:2d} walls in hand in total: wall = {beta[1] / beta[0]:+.2f} steps  (n={m.sum()})")

# does the wall value depend on who is ahead in the race?
print("\n   wall value by race state (linear + skill), in steps:")
for name, m in (("mover behind by 3+", dd <= -3), ("within 2", np.abs(dd) <= 2), ("mover ahead by 3+", dd >= 3)):
    X = np.column_stack([dd[m], wm[m], wo[m], sd[m], np.ones(m.sum())])
    beta = fit(X, y[m])
    print(f"      {name:20s}: my wall {beta[1] / beta[0]:+.2f}, opponent's wall {beta[2] / beta[0]:+.2f}  (n={m.sum()})")

# free form: marginal value of the k-th wall in hand (one-hot stash sizes, antisymmetric)
onehot = [(wm == k).astype(float) - (wo == k).astype(float) for k in range(1, 11)]
X = np.column_stack([dd] + onehot + [sd, np.ones_like(y)])
beta = fit(X, y, l2=1.0)
vals = [0.0] + list(beta[1:11] / beta[0])
print("\n   free-form stash value V(n), in steps:", "  ".join(f"{n}:{v:.1f}" for n, v in enumerate(vals)))
print("   marginal value of the n-th wall:      ", "  ".join(f"{n}:{vals[n] - vals[n-1]:+.1f}" for n in range(1, 11)))
