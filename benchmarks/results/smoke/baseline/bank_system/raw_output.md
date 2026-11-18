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
            raise ValueError("Deposit amount must be greater than zero")
        self.balance += amount

    def withdraw(self, amount: float):
        if amount <= 0:
            raise ValueError("Withdrawal amount must be greater than zero")
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
import sys
from bank import Bank

def parse_command(line: str):
    parts = line.split()
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
    elif parts[0] == "quit":
        return "quit"
    else:
        return None

def main():
    bank = Bank()

    for line in sys.stdin:
        command = parse_command(line.strip())
        if command is None:
            continue
        try:
            if command[0] == "open":
                bank.open_account(command[1], command[2])
            elif command[0] == "deposit":
                account = bank.get_account(command[1])
                if account is None:
                    raise KeyError("Owner does not have an account")
                account.deposit(command[2])
            elif command[0] == "withdraw":
                account = bank.get_account(command[1])
                if account is None:
                    raise KeyError("Owner does not have an account")
                account.withdraw(command[2])
            elif command[0] == "transfer":
                bank.transfer(command[1], command[2], command[3])
            elif command[0] == "balance":
                account = bank.get_account(command[1])
                if account is None:
                    raise KeyError("Owner does not have an account")
                print(f"{command[1]}: {account.balance:.2f}")
            elif command[0] == "quit":
                break
        except (ValueError, KeyError, InsufficientFundsError) as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
```