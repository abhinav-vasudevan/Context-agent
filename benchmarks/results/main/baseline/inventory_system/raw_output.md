### FILE: product.py
```python
class Product:
    def __init__(self, sku: str, name: str, price: float, quantity: int = 0):
        if price < 0:
            raise ValueError("Price cannot be negative")
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        self.sku = sku
        self.name = name
        self.price = price
        self.quantity = quantity
```

### FILE: inventory.py
```python
class Inventory:
    def __init__(self):
        self.products = {}

    def add_product(self, product):
        if product.sku in self.products:
            raise ValueError("Product with SKU already exists")
        self.products[product.sku] = product

    def get(self, sku):
        return self.products.get(sku)

    def restock(self, sku, qty):
        if qty <= 0:
            raise ValueError("Quantity to restock must be positive")
        product = self.get(sku)
        if product is None:
            raise KeyError("Unknown SKU")
        product.quantity += qty

    def sell(self, sku, qty):
        product = self.get(sku)
        if product is None:
            raise KeyError("Unknown SKU")
        if qty <= 0:
            raise ValueError("Quantity to sell must be positive")
        if qty > product.quantity:
            return 0.0
        sale_amount = product.price * qty
        product.quantity -= qty
        return sale_amount

    def total_value(self):
        return sum(product.price * product.quantity for product in self.products.values())

    def low_stock(self, threshold=5):
        return sorted([product.sku for product in self.products.values() if product.quantity < threshold])
```

### FILE: report.py
```python
def format_report(inventory):
    products = sorted(inventory.products.values(), key=lambda x: x.sku)
    total_value = inventory.total_value()
    lines = []
    for product in products:
        lines.append(f"{product.sku} | {product.name} | {product.quantity} | {product.price:.2f}")
    lines.append(f"TOTAL: {total_value:.2f}")
    return "\n".join(lines)
```

### FILE: main.py
```python
import sys
from product import Product
from inventory import Inventory
from report import format_report

def parse_add_command(args):
    if len(args) != 5:
        return None
    sku, price, quantity, name = args[1], float(args[2]), int(args[3]), " ".join(args[4:])
    return Product(sku, name, price, quantity)

def parse_sell_command(args):
    if len(args) != 3:
        return None
    sku, qty = args[1], int(args[2])
    return sku, qty

def parse_restock_command(args):
    if len(args) != 3:
        return None
    sku, qty = args[1], int(args[2])
    return sku, qty

def parse_report_command():
    return None

def main():
    inventory = Inventory()
    while True:
        line = sys.stdin.readline().strip()
        if line == "quit":
            break
        args = line.split()
        if args[0] == "add":
            product = parse_add_command(args)
            if product is not None:
                try:
                    inventory.add_product(product)
                except ValueError as e:
                    print(f"Error: {e}")
        elif args[0] == "sell":
            sku, qty = parse_sell_command(args)
            if sku is not None and qty is not None:
                try:
                    print(f"Sold: {inventory.sell(sku, qty):.2f}")
                except (ValueError, KeyError) as e:
                    print(f"Error: {e}")
        elif args[0] == "restock":
            sku, qty = parse_restock_command(args)
            if sku is not None and qty is not None:
                try:
                    inventory.restock(sku, qty)
                except (ValueError, KeyError) as e:
                    print(f"Error: {e}")
        elif args[0] == "report":
            print(format_report(inventory))
        else:
            print("Unknown command")

if __name__ == "__main__":
    main()
```