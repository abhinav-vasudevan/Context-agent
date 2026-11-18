class InsufficientFundsError(Exception):
    pass


class Account:
    def __init__(self, owner: str, balance: float = 0.0):
        self.owner = owner
        self.balance = float(balance)

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.balance += amount

    def withdraw(self, amount):
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self.balance:
            raise InsufficientFundsError("Insufficient funds")
        self.balance -= amount
