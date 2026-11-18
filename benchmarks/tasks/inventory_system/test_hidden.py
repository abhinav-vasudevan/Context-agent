import pytest
from discover import load_symbol, run_main


def _inv():
    Product = load_symbol("Product")
    Inventory = load_symbol("Inventory")
    inv = Inventory()
    inv.add_product(Product("B2", "stapler", 7.0, 3))
    inv.add_product(Product("A1", "pen", 2.5, 10))
    return inv, Product


def test_product_validation():
    Product = load_symbol("Product")
    with pytest.raises(ValueError):
        Product("X", "bad", -1.0, 1)
    with pytest.raises(ValueError):
        Product("Y", "bad", 1.0, -1)


def test_duplicate_sku_rejected():
    inv, Product = _inv()
    with pytest.raises(ValueError):
        inv.add_product(Product("A1", "other", 1.0, 1))


def test_restock_and_errors():
    inv, _ = _inv()
    inv.restock("B2", 4)
    assert inv.get("B2").quantity == 7
    with pytest.raises(ValueError):
        inv.restock("B2", 0)
    with pytest.raises(KeyError):
        inv.restock("ZZ", 1)


def test_sell_returns_amount_and_reduces_stock():
    inv, _ = _inv()
    assert inv.sell("A1", 4) == pytest.approx(10.0)
    assert inv.get("A1").quantity == 6


def test_oversell_rejected_and_stock_unchanged():
    inv, _ = _inv()
    with pytest.raises(ValueError):
        inv.sell("B2", 99)
    assert inv.get("B2").quantity == 3


def test_total_value_and_low_stock():
    inv, _ = _inv()
    assert inv.total_value() == pytest.approx(46.0)
    assert inv.low_stock() == ["B2"]
    assert inv.low_stock(threshold=20) == ["A1", "B2"]


def test_format_report():
    inv, _ = _inv()
    format_report = load_symbol("format_report")
    lines = [ln.strip() for ln in format_report(inv).strip().splitlines()]
    assert lines == ["A1 | pen | 10 | 2.50", "B2 | stapler | 3 | 7.00", "TOTAL: 46.00"]


def test_cli_end_to_end():
    out = run_main("add A1 2.50 10 blue pen\nadd B2 7 3 stapler\nsell A1 4\nsell B2 50\nreport\nquit\n")
    assert out.returncode == 0, out.stderr
    assert "Sold: 10.00" in out.stdout
    assert "Error:" in out.stdout
    assert "A1 | blue pen | 6 | 2.50" in out.stdout
    assert "TOTAL: 36.00" in out.stdout
