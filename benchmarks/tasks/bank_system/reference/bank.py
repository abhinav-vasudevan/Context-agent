from accounts import Account


class Bank:
    def __init__(self):
        self._accounts = {}

    def open_account(self, owner, initial_deposit=0.0):
        if owner in self._accounts:
            raise ValueError(f"{owner} already has an account")
        acct = Account(owner, initial_deposit)
        self._accounts[owner] = acct
        return acct

    def get_account(self, owner):
        if owner not in self._accounts:
            raise KeyError(owner)
        return self._accounts[owner]

    def transfer(self, from_owner, to_owner, amount):
        src = self.get_account(from_owner)
        dst = self.get_account(to_owner)
        src.withdraw(amount)
        try:
            dst.deposit(amount)
        except Exception:
            src.balance += amount
            raise

    def total_deposits(self):
        return sum(a.balance for a in self._accounts.values())
