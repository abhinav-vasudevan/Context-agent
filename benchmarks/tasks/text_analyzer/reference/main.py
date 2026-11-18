import sys

from stats import sentence_count, top_words
from tokenizer import tokenize


def main():
    text = sys.stdin.read()
    tokens = tokenize(text)
    print(f"Words: {len(tokens)}")
    print(f"Unique: {len(set(tokens))}")
    print(f"Sentences: {sentence_count(text)}")
    print("Top: " + ", ".join(f"{w} ({c})" for w, c in top_words(tokens, 3)))


if __name__ == "__main__":
    main()
