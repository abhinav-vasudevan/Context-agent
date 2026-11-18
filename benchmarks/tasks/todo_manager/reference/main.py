import sys

from todo_list import TodoList


def main():
    todos = TodoList()
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "quit":
            break
        try:
            if parts[0] == "add":
                task = todos.add(" ".join(parts[2:]), int(parts[1]))
                print(f"Added task {task.id}")
            elif parts[0] == "done":
                todos.complete(int(parts[1]))
            elif parts[0] == "list":
                for t in todos.pending():
                    print(f"{t.id}. [P{t.priority}] {t.title}")
            else:
                raise ValueError(f"unknown command {parts[0]}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
