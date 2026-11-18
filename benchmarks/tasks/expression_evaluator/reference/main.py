import sys

from evaluator import evaluate


def fmt(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{round(value, 6):.6f}".rstrip("0").rstrip(".")


def main():
    for line in sys.stdin:
        line = line.strip()
        if line == "quit":
            break
        if not line:
            continue
        try:
            print(fmt(evaluate(line)))
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
