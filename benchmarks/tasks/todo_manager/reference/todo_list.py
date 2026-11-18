import json
from dataclasses import asdict

from models import Task


class TodoList:
    def __init__(self):
        self._tasks = {}
        self._next_id = 1

    def add(self, title, priority=2):
        if not title or not title.strip():
            raise ValueError("Title must not be empty")
        if priority not in (1, 2, 3):
            raise ValueError("Priority must be 1, 2 or 3")
        task = Task(self._next_id, title.strip(), priority)
        self._tasks[task.id] = task
        self._next_id += 1
        return task

    def complete(self, task_id):
        if task_id not in self._tasks:
            raise KeyError(task_id)
        self._tasks[task_id].done = True

    def remove(self, task_id):
        if task_id not in self._tasks:
            raise KeyError(task_id)
        del self._tasks[task_id]

    def pending(self):
        return sorted((t for t in self._tasks.values() if not t.done), key=lambda t: (t.priority, t.id))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(t) for t in self._tasks.values()], f)

    @classmethod
    def load(cls, path):
        inst = cls()
        with open(path, encoding="utf-8") as f:
            for row in json.load(f):
                task = Task(**row)
                inst._tasks[task.id] = task
        inst._next_id = max(inst._tasks, default=0) + 1
        return inst
