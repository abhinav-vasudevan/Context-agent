import sys

from bank import Bank


def handle(bank, parts):
    cmd = parts[0]
    if cmd == "open":
        bank.open_account(parts[1], float(parts[2]))
    elif cmd == "deposit":
        bank.get_account(parts[1]).deposit(float(parts[2]))
    elif cmd == "withdraw":
        bank.get_account(parts[1]).withdraw(float(parts[2]))
    elif cmd == "transfer":
        bank.transfer(parts[1], parts[2], float(parts[3]))
    elif cmd == "balance":
        print(f"{parts[1]}: {bank.get_account(parts[1]).balance:.2f}")
    else:
        raise ValueError(f"unknown command {cmd}")


def main():
    bank = Bank()
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "quit":
            break
        try:
            handle(bank, parts)
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
