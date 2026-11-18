LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


class Board:
    def __init__(self):
        self.cells = [None] * 9

    def current_player(self):
        filled = sum(c is not None for c in self.cells)
        return "X" if filled % 2 == 0 else "O"

    def make_move(self, index, player):
        if not isinstance(index, int) or not 0 <= index <= 8:
            raise ValueError("index must be 0-8")
        if self.winner() or self.is_full():
            raise ValueError("game is over")
        if self.cells[index] is not None:
            raise ValueError("cell occupied")
        if player != self.current_player():
            raise ValueError(f"not {player}'s turn")
        self.cells[index] = player

    def winner(self):
        for a, b, c in LINES:
            if self.cells[a] and self.cells[a] == self.cells[b] == self.cells[c]:
                return self.cells[a]
        return None

    def is_full(self):
        return all(c is not None for c in self.cells)

    def available_moves(self):
        return [i for i, c in enumerate(self.cells) if c is None]

    def copy(self):
        b = Board()
        b.cells = list(self.cells)
        return b

    def render(self):
        rows = []
        for r in range(3):
            rows.append(" | ".join(self.cells[3 * r + c] or str(3 * r + c) for c in range(3)))
        return "\n---------\n".join(rows)
