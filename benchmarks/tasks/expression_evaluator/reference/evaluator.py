from lexer import tokenize


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise ValueError("Unexpected end of expression")
        self.pos += 1
        return tok

    def expr(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            rhs = self.term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def term(self):
        value = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            rhs = self.unary()
            if op == "*":
                value *= rhs
            else:
                if rhs == 0:
                    raise ZeroDivisionError("division by zero")
                value /= rhs
        return value

    def unary(self):
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == "^":
            self.take()
            return base ** self.unary()
        return base

    def atom(self):
        tok = self.take()
        if tok == "(":
            value = self.expr()
            if self.take() != ")":
                raise ValueError("Expected ')'")
            return value
        try:
            return float(tok)
        except ValueError:
            raise ValueError(f"Unexpected token {tok!r}") from None


def evaluate(expr):
    tokens = tokenize(expr)
    if not tokens:
        raise ValueError("Empty expression")
    parser = _Parser(tokens)
    value = parser.expr()
    if parser.peek() is not None:
        raise ValueError(f"Unexpected token {parser.peek()!r}")
    return value
