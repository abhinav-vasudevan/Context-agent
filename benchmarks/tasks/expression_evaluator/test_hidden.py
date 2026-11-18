import pytest
from discover import load_symbol, run_main


def test_tokenize_example():
    tokenize = load_symbol("tokenize")
    assert tokenize("2*(3+4.5)") == ["2", "*", "(", "3", "+", "4.5", ")"]


def test_tokenize_rejects_invalid_characters():
    tokenize = load_symbol("tokenize")
    with pytest.raises(ValueError):
        tokenize("2 & 3")


def test_precedence_and_parentheses():
    evaluate = load_symbol("evaluate")
    assert evaluate("2 + 3 * 4") == pytest.approx(14)
    assert evaluate("(2 + 3) * 4") == pytest.approx(20)
    assert evaluate("10 - 4 - 3") == pytest.approx(3)
    assert evaluate("8 / 4 / 2") == pytest.approx(1)


def test_power_is_right_associative():
    evaluate = load_symbol("evaluate")
    assert evaluate("2 ^ 3 ^ 2") == pytest.approx(512)
    assert evaluate("2 * 3 ^ 2") == pytest.approx(18)


def test_unary_minus():
    evaluate = load_symbol("evaluate")
    assert evaluate("-3 + 5") == pytest.approx(2)
    assert evaluate("2 * -3") == pytest.approx(-6)
    assert evaluate("-(1 + 2)") == pytest.approx(-3)


def test_decimals():
    evaluate = load_symbol("evaluate")
    assert evaluate("1.5 * 4") == pytest.approx(6.0)


def test_errors():
    evaluate = load_symbol("evaluate")
    with pytest.raises(ZeroDivisionError):
        evaluate("1 / 0")
    for bad in ("2 +", "(1 + 2", ""):
        with pytest.raises(ValueError):
            evaluate(bad)


def test_cli_end_to_end():
    out = run_main("2 + 3 * 4\n1 / 2\n10 / 3\n1 / 0\n(1 +\nquit\n")
    assert out.returncode == 0, out.stderr
    lines = [ln.strip() for ln in out.stdout.strip().splitlines() if ln.strip()]
    assert lines[:3] == ["14", "0.5", "3.333333"]
    assert sum(ln.startswith("Error:") for ln in lines) == 2
