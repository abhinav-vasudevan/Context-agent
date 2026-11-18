import itertools

import pytest
from discover import load_symbol, run_main


def _board(moves):
    Board = load_symbol("Board")
    b = Board()
    for i, m in enumerate(moves):
        b.make_move(m, "X" if i % 2 == 0 else "O")
    return b


def test_turn_order_and_invalid_moves():
    Board = load_symbol("Board")
    b = Board()
    assert b.current_player() == "X"
    with pytest.raises(ValueError):
        b.make_move(0, "O")
    b.make_move(4, "X")
    assert b.current_player() == "O"
    with pytest.raises(ValueError):
        b.make_move(4, "O")
    with pytest.raises(ValueError):
        b.make_move(9, "O")


def test_winner_detection_rows_cols_diagonals():
    assert _board([0, 3, 1, 4, 2]).winner() == "X"        # top row
    assert _board([1, 0, 2, 3, 8, 6]).winner() == "O"     # left column
    assert _board([0, 1, 4, 2, 8]).winner() == "X"        # diagonal
    assert _board([0, 1]).winner() is None


def test_full_board_and_available_moves():
    b = _board([0, 1, 2, 4, 3, 5, 7, 6, 8])  # draw
    assert b.is_full() and b.winner() is None
    assert b.available_moves() == []
    assert _board([4]).available_moves() == [0, 1, 2, 3, 5, 6, 7, 8]


def test_no_moves_after_game_over():
    b = _board([0, 3, 1, 4, 2])
    with pytest.raises(ValueError):
        b.make_move(5, "O")


def test_copy_is_independent():
    b = _board([4])
    c = b.copy()
    c.make_move(0, "O")
    assert 0 in b.available_moves()


def test_ai_takes_win_and_blocks():
    best_move = load_symbol("best_move")
    # O to move, O can win at 5 (3,4,5)
    assert best_move(_board([0, 3, 1, 4, 8])) == 5
    # O to move, must block X at 2 (0,1,2)
    assert best_move(_board([0, 4, 1])) == 2


def test_ai_never_loses_against_every_x_strategy():
    """Exhaustively play every possible X move sequence against best_move."""
    best_move = load_symbol("best_move")

    def play(b):
        if b.winner() or b.is_full():
            return b.winner()
        if b.current_player() == "O":
            nb = b.copy()
            nb.make_move(best_move(nb), "O")
            return play(nb)
        results = set()
        for m in b.available_moves():
            nb = b.copy()
            nb.make_move(m, "X")
            results.add(play(nb))
        return "X" if "X" in results else None

    Board = load_symbol("Board")
    assert play(Board()) != "X"


def test_cli_game_ends_without_x_winning():
    out = run_main("4\n4\n0\n2\n6\n8\n1\n3\n5\n7\n")
    assert out.returncode == 0, out.stderr
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    assert any(ln.startswith("Error:") for ln in lines)      # 2nd "4" is occupied
    final = [ln for ln in lines if ln in ("Winner: X", "Winner: O", "Draw")]
    assert len(final) == 1 and final[0] != "Winner: X"
