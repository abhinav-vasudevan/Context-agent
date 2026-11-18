### FILE: accounts.py
```python
class InsufficientFundsError(Exception):
    pass

class Account:
    def __init__(self, owner: str, balance: float = 0.0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount: float):
        if amount <= 0:
            raise ValueError("Invalid deposit amount")
        self.balance += amount

    def withdraw(self, amount: float):
        if amount <= 0:
            raise ValueError("Invalid withdrawal amount")
        if amount > self.balance:
            raise InsufficientFundsError("Insufficient funds")
        self.balance -= amount
```

### FILE: bank.py
```python
class Bank:
    def __init__(self):
        self.accounts = {}

    def open_account(self, owner: str, initial_deposit: float = 0.0):
        if owner in self.accounts:
            raise ValueError("Owner already has an account")
        self.accounts[owner] = Account(owner, initial_deposit)

    def get_account(self, owner: str):
        return self.accounts.get(owner)

    def transfer(self, from_owner: str, to_owner: str, amount: float):
        from_account = self.get_account(from_owner)
        to_account = self.get_account(to_owner)
        if from_account is None or to_account is None:
            raise KeyError("One or both owners do not have an account")
        try:
            from_account.withdraw(amount)
            to_account.deposit(amount)
        except (ValueError, InsufficientFundsError) as e:
            raise e

    def total_deposits(self):
        return sum(account.balance for account in self.accounts.values())
```

### FILE: main.py
```python
import bank
import sys

def parse_command(command: str):
    parts = command.split()
    if parts[0] == "open":
        return "open", parts[1], float(parts[2])
    elif parts[0] == "deposit":
        return "deposit", parts[1], float(parts[2])
    elif parts[0] == "withdraw":
        return "withdraw", parts[1], float(parts[2])
    elif parts[0] == "transfer":
        return "transfer", parts[1], parts[2], float(parts[3])
    elif parts[0] == "balance":
        return "balance", parts[1]
    else:
        return None

def main():
    bank_instance = bank.Bank()
    while True:
        command = input()
        if command == "quit":
            break
        parsed_command = parse_command(command)
        if parsed_command is None:
            continue
        action, *args = parsed_command
        try:
            if action == "open":
                bank_instance.open_account(args[0], args[1])
            elif action == "deposit":
                account = bank_instance.get_account(args[0])
                if account is not None:
                    account.deposit(args[1])
            elif action == "withdraw":
                account = bank_instance.get_account(args[0])
                if account is not None:
                    account.withdraw(args[1])
            elif action == "transfer":
                bank_instance.transfer(args[0], args[1], args[2])
            elif action == "balance":
                account = bank_instance.get_account(args[0])
                if account is not None:
                    print(f"{args[0]}: {account.balance:.2f}")
        except (ValueError, KeyError, bank.InsufficientFundsError) as e:
            print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
```