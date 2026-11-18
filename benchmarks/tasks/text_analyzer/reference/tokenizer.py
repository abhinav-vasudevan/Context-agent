import re


def tokenize(text):
    words = []
    for run in re.findall(r"[A-Za-z0-9']+", text):
        word = run.strip("'").lower()
        if word:
            words.append(word)
    return words
