import re
from collections import Counter


def word_frequencies(tokens):
    return dict(Counter(tokens))


def top_words(tokens, n):
    return sorted(Counter(tokens).items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def average_word_length(tokens):
    return sum(len(t) for t in tokens) / len(tokens) if tokens else 0.0


def sentence_count(text):
    if not re.search(r"[A-Za-z0-9]", text):
        return 0
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts[:-1]) + (1 if parts[-1].strip() else 0)
