class Product:
    def __init__(self, sku: str, name: str, price: float, quantity: int = 0):
        if price < 0:
            raise ValueError("price must be >= 0")
        if quantity < 0:
            raise ValueError("quantity must be >= 0")
        self.sku = sku
        self.name = name
        self.price = float(price)
        self.quantity = int(quantity)
