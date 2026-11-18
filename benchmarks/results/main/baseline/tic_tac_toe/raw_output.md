### FILE: board.py
```python
class Board:
    def __init__(self):
        self.cells = [" "] * 9

    def make_move(self, index, player):
        if index < 0 or index > 8:
            raise ValueError("Index out of range")
        if self.cells[index] != " ":
            raise ValueError("Cell already occupied")
        if player != self.current_player():
            raise ValueError("Not that player's turn")
        self.cells[index] = player

    def current_player(self):
        x_moves = self.cells.count("X")
        o_moves = self.cells.count("O")
        return "X" if x_moves == o_moves else "O"

    def winner(self):
        winning_combinations = [
            (0, 1, 2),
            (3, 4, 5),
            (6, 7, 8),
            (0, 3, 6),
            (1, 4, 7),
            (2, 5, 8),
            (0, 4, 8),
            (2, 4, 6)
        ]
        for combination in winning_combinations:
            if self.cells[combination[0]] == self.cells[combination[1]] == self.cells[combination[2]] != " ":
                return self.cells[combination[0]]
        if self.is_full():
            return None
        return None

    def is_full(self):
        return all(cell != " " for cell in self.cells)

    def available_moves(self):
        return sorted([i for i, cell in enumerate(self.cells) if cell == " "])

    def copy(self):
        new_board = Board()
        new_board.cells = self.cells[:]
        return new_board
```

### FILE: ai.py
```python
def best_move(board):
    current_player = board.current_player()
    opponent = "O" if current_player == "X" else "X"

    for move in board.available_moves():
        new_board = board.copy()
        new_board.make_move(move, current_player)
        result = new_board.winner()
        if result == current_player:
            return move
        elif result == opponent:
            continue
        else:
            return move

    # If no immediate win or block, just make a random move
    return board.available_moves()[0]
```

### FILE: main.py
```python
import sys
import board
import ai

def print_board(board):
    print(f"{board.cells[0]} | {board.cells[1]} | {board.cells[2]}")
    print("---------")
    print(f"{board.cells[3]} | {board.cells[4]} | {board.cells[5]}")
    print("---------")
    print(f"{board.cells[6]} | {board.cells[7]} | {board.cells[8]}")

def main():
    board = board.Board()
    while True:
        try:
            x_move = int(input("Enter X's move (0-8): "))
            board.make_move(x_move, "X")
            print_board(board)
            winner = board.winner()
            if winner is not None:
                print(f"Winner: {winner}")
                break
            o_move = ai.best_move(board)
            board.make_move(o_move, "O")
            print_board(board)
            winner = board.winner()
            if winner is not None:
                print(f"Winner: {winner}")
                break
        except ValueError as e:
            print(f"Error: {e}")
            continue

if __name__ == "__main__":
    main()
```