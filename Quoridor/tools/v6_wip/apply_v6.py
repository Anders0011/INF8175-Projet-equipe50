"""V6 evaluation change: python apply_v6.py <v5 my_player.py> <target.py>. Every edit must match exactly once."""
import sys

src = open(sys.argv[1], encoding="utf-8").read()


def sub(old: str, new: str) -> None:
    global src
    assert src.count(old) == 1, (src.count(old), old[:70])
    src = src.replace(old, new)


sub('''W_WALLS = 124              # one wall in hand, about 1.24 steps (fitted on game outcomes)
''', '''W_WALLS = 124              # one wall in hand, about 1.24 steps (fitted on game outcomes)
WALL_FIGHT_START = 12      # walls in hand, both players together, below which a wall has its full value
W_WALLS_EARLY = 0          # less per wall in hand above that total: walls are cheap while the board is open
''')

sub('''class MyPlayer(PlayerQuoridor):''', '''def _wall_table() -> list[list[int]]:
    """table[mine][theirs]: value of the walls in hand, for the player holding `mine`."""
    table = []
    for mine in range(32):
        row = []
        for theirs in range(32):
            value = max(0, W_WALLS - W_WALLS_EARLY * max(0, mine + theirs - WALL_FIGHT_START))
            row.append(value * (mine - theirs))
        table.append(row)
    return table


class MyPlayer(PlayerQuoridor):''')

sub('''        self._tt = {}            # transposition table: key -> (depth, value, flag, best move)
''', '''        self._tt = {}            # transposition table: key -> (depth, value, flag, best move)
        self._wall_table = _wall_table()
''')

sub('''        walls_term = W_WALLS * (board.walls_left[turn] - board.walls_left[other])
''', '''        mine, theirs = board.walls_left[turn], board.walls_left[other]
        walls_term = self._wall_table[mine][theirs]
''')

sub('''            pawns = board.pawns
            here = pawns[turn]
''', '''            pawns = board.pawns
            here = pawns[turn]
            walls_term_after_wall = self._wall_table[mine - 1][theirs] if mine else 0
''')

sub('''                    value = W_DISTANCE * (after_op - after_me) + walls_term - W_WALLS - TEMPO
''', '''                    value = W_DISTANCE * (after_op - after_me) + walls_term_after_wall - TEMPO
''')

compile(src, sys.argv[2], "exec")
with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as handle:
    handle.write(src)
print(f"{sys.argv[2]}: {len(src.splitlines())} lines")
