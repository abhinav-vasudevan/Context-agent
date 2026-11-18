class Inventory:
    def __init__(self):
        self._products = {}

    def add_product(self, product):
        if product.sku in self._products:
            raise ValueError(f"duplicate sku {product.sku}")
        self._products[product.sku] = product

    def get(self, sku):
        if sku not in self._products:
            raise KeyError(sku)
        return self._products[sku]

    def products(self):
        return [self._products[k] for k in sorted(self._products)]

    def restock(self, sku, qty):
        product = self.get(sku)
        if qty <= 0:
            raise ValueError("qty must be positive")
        product.quantity += qty

    def sell(self, sku, qty):
        product = self.get(sku)
        if qty <= 0 or qty > product.quantity:
            raise ValueError("invalid quantity")
        product.quantity -= qty
        return product.price * qty

    def total_value(self):
        return sum(p.price * p.quantity for p in self._products.values())

    def low_stock(self, threshold=5):
        return sorted(p.sku for p in self._products.values() if p.quantity < threshold)
