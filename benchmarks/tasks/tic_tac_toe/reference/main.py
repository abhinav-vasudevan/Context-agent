import sys

from ai import best_move
from board import Board


def finished(board):
    w = board.winner()
    if w:
        print(f"Winner: {w}")
        return True
    if board.is_full():
        print("Draw")
        return True
    return False


def main():
    board = Board()
    print(board.render())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            board.make_move(int(line), "X")
        except Exception as e:
            print(f"Error: {e}")
            continue
        print(board.render())
        if finished(board):
            return
        board.make_move(best_move(board), "O")
        print(board.render())
        if finished(board):
            return


if __name__ == "__main__":
    main()
