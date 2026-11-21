"""Per-ply table of every Abyss game: distances, walls in hand, who moved, who won.
    python build_table.py <quoridor_dir> <fights.pkl> <out.pkl>
"""
import pickle
import sys

sys.path.insert(0, sys.argv[1])
import my_player  # noqa: E402
from actions_quoridor import Orientation, Wall  # noqa: E402


class Seat:
    def __init__(self, pid, goal):
        self.id, self.goal = pid, goal

    def get_goal_row(self):
        return self.goal


class Box:
    pass


games = [g for g in pickle.load(open(sys.argv[2], "rb")) if "error" not in g]
out = []
for g in games:
    ids = list(g["players"])            # index 0 / 1
    if len(g["winners"]) != 1:
        continue
    winner = ids.index(g["winners"][0])
    seats = [Seat(pid, g["players"][pid]["goal_row"]) for pid in ids]
    tags = [g["players"][pid]["name"].split("#")[-1] for pid in ids]
    plies = []
    for active, pawns, walls_left, _, walls in g["seq"]:
        state = Box()
        state.players = seats
        state.rep = Box()
        state.rep.dimension = 9
        state.rep.pawn_positions = pawns
        state.rep.remaining_walls = walls_left
        state.rep.walls = {Wall(r, c, Orientation.HORIZONTAL if o == "H" else Orientation.VERTICAL) for r, c, o in walls}
        state.active_player = seats[ids.index(active)]
        board = my_player._Board(state, ids[0])
        plies.append((ids.index(active), board.distance(0), board.distance(1), walls_left[ids[0]], walls_left[ids[1]]))
    out.append({"id": g["id"], "tags": tags, "winner": winner, "plies": plies})
pickle.dump(out, open(sys.argv[3], "wb"))
print(len(out), "games,", sum(len(g["plies"]) for g in out), "positions")
