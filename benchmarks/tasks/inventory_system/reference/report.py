def format_report(inventory) -> str:
    lines = [f"{p.sku} | {p.name} | {p.quantity} | {p.price:.2f}" for p in inventory.products()]
    lines.append(f"TOTAL: {inventory.total_value():.2f}")
    return "\n".join(lines)
