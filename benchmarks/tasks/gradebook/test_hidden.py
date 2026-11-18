import csv

import pytest
from discover import load_symbol, run_main


def _book():
    GradeBook = load_symbol("GradeBook")
    g = GradeBook()
    for s in ("alice", "bob", "carol", "dan"):
        g.add_student(s)
    g.add_grade("alice", "math", 95)
    g.add_grade("alice", "art", 88)
    g.add_grade("bob", "math", 70)
    g.add_grade("carol", "math", 91.5)
    return g, GradeBook


def test_letter_grade_boundaries():
    letter_grade = load_symbol("letter_grade")
    assert [letter_grade(s) for s in (90, 89.99, 80, 79.5, 70, 60, 59.9)] == ["A", "B", "B", "C", "C", "D", "F"]


def test_validation():
    g, _ = _book()
    with pytest.raises(ValueError):
        g.add_student("alice")
    with pytest.raises(KeyError):
        g.add_grade("zed", "math", 50)
    with pytest.raises(ValueError):
        g.add_grade("bob", "math", 101)


def test_averages():
    g, _ = _book()
    assert g.average("alice") == pytest.approx(91.5)
    assert g.subject_average("math") == pytest.approx((95 + 70 + 91.5) / 3)
    with pytest.raises(ValueError):
        g.average("dan")
    with pytest.raises(ValueError):
        g.subject_average("history")


def test_ranking_ties_and_excludes_ungraded():
    g, _ = _book()
    assert g.ranking() == ["alice", "carol", "bob"]


def test_csv_roundtrip(tmp_path):
    g, GradeBook = _book()
    path = tmp_path / "grades.csv"
    g.to_csv(str(path))
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["name", "subject", "score"]
    assert len(rows) == 5
    loaded = GradeBook.from_csv(str(path))
    assert loaded.average("alice") == pytest.approx(91.5)
    assert loaded.ranking() == ["alice", "carol", "bob"]


def test_cli_end_to_end():
    out = run_main(
        "student alice\nstudent bob\ngrade alice math 95\ngrade alice art 88\n"
        "grade bob math 72\ngrade bob art 150\nreport\nquit\n"
    )
    assert out.returncode == 0, out.stderr
    lines = [ln.strip() for ln in out.stdout.splitlines()]
    assert "1. alice 91.5 A" in lines
    assert "2. bob 72.0 C" in lines
    assert any(ln.startswith("Error:") for ln in lines)
