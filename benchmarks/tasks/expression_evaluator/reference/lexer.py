import re

_TOKEN = re.compile(r"\s*(?:(\d+\.\d*|\.\d+|\d+)|(.))")


def tokenize(expr):
    tokens = []
    for number, other in _TOKEN.findall(expr):
        if number:
            tokens.append(number)
        elif other.strip():
            if other not in "+-*/^()":
                raise ValueError(f"Invalid character: {other!r}")
            tokens.append(other)
    return tokens
