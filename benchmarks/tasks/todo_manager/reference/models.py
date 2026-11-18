from dataclasses import dataclass


@dataclass
class Task:
    id: int
    title: str
    priority: int
    done: bool = False
