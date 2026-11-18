from functools import lru_cache

from board import Board


@lru_cache(maxsize=None)
def _minimax(cells, me, depth):
    """Score from `me`'s point of view; faster wins / slower losses score higher."""
    b = Board()
    b.cells = list(cells)
    w = b.winner()
    if w:
        return (10 - depth) if w == me else (depth - 10)
    if b.is_full():
        return 0
    turn = b.current_player()
    scores = []
    for m in b.available_moves():
        nb = b.copy()
        nb.make_move(m, turn)
        scores.append(_minimax(tuple(nb.cells), me, depth + 1))
    return max(scores) if turn == me else min(scores)


def best_move(board):
    me = board.current_player()
    best, best_score = None, None
    for m in board.available_moves():
        nb = board.copy()
        nb.make_move(m, me)
        s = _minimax(tuple(nb.cells), me, 1)
        if best_score is None or s > best_score:
            best, best_score = m, s
    return best
