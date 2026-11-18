import pytest
from discover import load_symbol, run_main


def test_tokenize_example():
    tokenize = load_symbol("tokenize")
    assert tokenize("Hello, world! It's 2024.") == ["hello", "world", "it's", "2024"]


def test_tokenize_strips_edge_apostrophes():
    tokenize = load_symbol("tokenize")
    assert tokenize("'quoted' words -- and ' alone") == ["quoted", "words", "and", "alone"]


def test_word_frequencies():
    word_frequencies = load_symbol("word_frequencies")
    assert word_frequencies(["a", "b", "a"]) == {"a": 2, "b": 1}


def test_top_words_tie_break_alphabetical():
    top_words = load_symbol("top_words")
    tokens = ["pear", "apple", "pear", "fig", "apple", "kiwi"]
    assert top_words(tokens, 3) == [("apple", 2), ("pear", 2), ("fig", 1)]


def test_average_word_length():
    average_word_length = load_symbol("average_word_length")
    assert average_word_length(["ab", "abcd"]) == pytest.approx(3.0)
    assert average_word_length([]) == 0.0


def test_sentence_count():
    sentence_count = load_symbol("sentence_count")
    assert sentence_count("One. Two! Three?") == 3
    assert sentence_count("Wait... what?! Yes") == 3
    assert sentence_count("no terminator") == 1
    assert sentence_count("   ") == 0


def test_cli_end_to_end():
    out = run_main("The cat sat. The cat ran!\nThe end?")
    assert out.returncode == 0, out.stderr
    lines = [ln.strip() for ln in out.stdout.strip().splitlines()]
    assert "Words: 8" in lines
    assert "Unique: 5" in lines
    assert "Sentences: 3" in lines
    assert "Top: the (3), cat (2), end (1)" in lines
