ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def encode_base62(n: int) -> str:
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, 62)
        out.append(ALPHABET[r])
    return "".join(reversed(out))


def decode_base62(s: str) -> int:
    if not s:
        raise ValueError("empty code")
    n = 0
    for ch in s:
        idx = ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"invalid character {ch!r}")
        n = n * 62 + idx
    return n
