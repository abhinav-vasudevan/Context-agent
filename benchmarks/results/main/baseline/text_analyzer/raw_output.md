### FILE: tokenizer.py
```python
import re

def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [re.sub(r"^'|'$", "", word) for word in words if word]
```

### FILE: stats.py
```python
from collections import Counter
import math

def word_frequencies(tokens: list[str]) -> dict[str, int]:
    return Counter(tokens)

def top_words(tokens: list[str], n: int) -> list[tuple[str, int]]:
    freqs = word_frequencies(tokens)
    return sorted(freqs.most_common(n), key=lambda x: (-x[1], x[0]))

def average_word_length(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    return sum(len(word) for word in tokens) / len(tokens)

def sentence_count(text: str) -> int:
    if not text:
        return 0
    sentences = re.findall(r"[.!?]+", text)
    return len(sentences) + (text[-1].isalnum() and not text[-1] in sentences)
```

### FILE: main.py
```python
import sys
from stats import sentence_count, word_frequencies, top_words, average_word_length
from tokenizer import tokenize

if __name__ == "__main__":
    text = sys.stdin.read()
    tokens = tokenize(text)
    words = len(tokens)
    unique = len(set(tokens))
    sentences = sentence_count(text)
    top = top_words(tokens, min(3, unique))
    avg_len = average_word_length(tokens)
    print(f"Words: {words}")
    print(f"Unique: {unique}")
    print(f"Sentences: {sentences}")
    top_str = ", ".join(f"{word} ({count})" for word, count in top)
    print(f"Top: {top_str}")
```