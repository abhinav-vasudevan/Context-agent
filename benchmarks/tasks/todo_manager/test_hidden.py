import pytest
from discover import load_symbol, run_main


def test_ids_start_at_one_and_increment():
    TodoList = load_symbol("TodoList")
    t = TodoList()
    a = t.add("first")
    b = t.add("second", 1)
    assert (a.id, b.id) == (1, 2)
    assert a.priority == 2 and a.done is False


def test_validation():
    TodoList = load_symbol("TodoList")
    t = TodoList()
    with pytest.raises(ValueError):
        t.add("   ")
    with pytest.raises(ValueError):
        t.add("x", 4)


def test_pending_sorted_by_priority_then_id():
    TodoList = load_symbol("TodoList")
    t = TodoList()
    t.add("c", 3)
    t.add("a", 1)
    t.add("b", 2)
    t.add("a2", 1)
    assert [x.title for x in t.pending()] == ["a", "a2", "b", "c"]


def test_complete_and_remove():
    TodoList = load_symbol("TodoList")
    t = TodoList()
    t.add("one")
    t.add("two")
    t.complete(1)
    assert [x.id for x in t.pending()] == [2]
    t.remove(2)
    assert t.pending() == []
    with pytest.raises(KeyError):
        t.complete(99)
    with pytest.raises(KeyError):
        t.remove(99)


def test_save_and_load_roundtrip(tmp_path):
    TodoList = load_symbol("TodoList")
    t = TodoList()
    t.add("keep", 1)
    t.add("finish", 3)
    t.complete(2)
    path = tmp_path / "todo.json"
    t.save(str(path))
    loaded = TodoList.load(str(path))
    assert [(x.id, x.title, x.priority) for x in loaded.pending()] == [(1, "keep", 1)]
    assert loaded.add("new").id == 3


def test_task_dataclass_fields():
    Task = load_symbol("Task")
    task = Task(id=7, title="t", priority=1)
    assert task.done is False


def test_cli_end_to_end():
    out = run_main("add 3 write report\nadd 1 buy milk\ndone 1\nadd 2 call bob\nlist\ndone 42\nquit\n")
    assert out.returncode == 0, out.stderr
    assert "Added task 1" in out.stdout and "Added task 3" in out.stdout
    lines = [ln.strip() for ln in out.stdout.splitlines()]
    assert "2. [P1] buy milk" in lines
    assert "3. [P2] call bob" in lines
    assert lines.index("2. [P1] buy milk") < lines.index("3. [P2] call bob")
    assert not any(ln.startswith("1.") for ln in lines)
    assert "Error:" in out.stdout
