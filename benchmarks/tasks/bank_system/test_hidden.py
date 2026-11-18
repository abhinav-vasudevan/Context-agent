import pytest
from discover import load_symbol, run_main


def test_deposit_and_withdraw():
    Account = load_symbol("Account")
    a = Account("alice", 100.0)
    a.deposit(50)
    a.withdraw(30)
    assert a.balance == pytest.approx(120.0)
    assert a.owner == "alice"


def test_invalid_amounts_raise_value_error():
    Account = load_symbol("Account")
    a = Account("bob")
    with pytest.raises(ValueError):
        a.deposit(0)
    with pytest.raises(ValueError):
        a.withdraw(-5)


def test_overdraw_raises_insufficient_funds():
    Account = load_symbol("Account")
    Insufficient = load_symbol("InsufficientFundsError")
    a = Account("carol", 10.0)
    with pytest.raises(Insufficient):
        a.withdraw(11)
    assert a.balance == pytest.approx(10.0)


def test_duplicate_account_and_missing_account():
    Bank = load_symbol("Bank")
    b = Bank()
    b.open_account("dave", 5)
    with pytest.raises(ValueError):
        b.open_account("dave")
    with pytest.raises(KeyError):
        b.get_account("nobody")


def test_transfer_moves_money():
    Bank = load_symbol("Bank")
    b = Bank()
    b.open_account("a", 100)
    b.open_account("b", 0)
    b.transfer("a", "b", 40)
    assert b.get_account("a").balance == pytest.approx(60)
    assert b.get_account("b").balance == pytest.approx(40)


def test_failed_transfer_is_atomic():
    Bank = load_symbol("Bank")
    b = Bank()
    b.open_account("a", 30)
    b.open_account("b", 10)
    with pytest.raises(Exception):
        b.transfer("a", "b", 500)
    assert b.get_account("a").balance == pytest.approx(30)
    assert b.get_account("b").balance == pytest.approx(10)


def test_total_deposits():
    Bank = load_symbol("Bank")
    b = Bank()
    b.open_account("x", 10)
    b.open_account("y", 15.5)
    assert b.total_deposits() == pytest.approx(25.5)


def test_cli_end_to_end():
    out = run_main("open alice 100\ndeposit alice 50\nwithdraw alice 30\nbalance alice\nwithdraw alice 1000\nbalance alice\nquit\n")
    assert out.returncode == 0, out.stderr
    assert "alice: 120.00" in out.stdout
    assert "Error:" in out.stdout
