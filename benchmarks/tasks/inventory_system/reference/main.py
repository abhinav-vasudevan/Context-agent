import sys

from inventory import Inventory
from product import Product
from report import format_report


def main():
    inv = Inventory()
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "quit":
            break
        try:
            if parts[0] == "add":
                inv.add_product(Product(parts[1], " ".join(parts[4:]), float(parts[2]), int(parts[3])))
            elif parts[0] == "sell":
                print(f"Sold: {inv.sell(parts[1], int(parts[2])):.2f}")
            elif parts[0] == "restock":
                inv.restock(parts[1], int(parts[2]))
            elif parts[0] == "report":
                print(format_report(inv))
            else:
                raise ValueError(f"unknown command {parts[0]}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
