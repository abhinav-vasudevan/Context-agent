import sys

from shortener import Shortener


def main():
    s = Shortener()
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "quit":
            break
        try:
            if parts[0] == "shorten":
                print(s.shorten(parts[1]))
            elif parts[0] == "expand":
                print(s.expand(parts[1]))
            elif parts[0] == "clicks":
                print(s.clicks(parts[1]))
            else:
                raise ValueError(f"unknown command {parts[0]}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
