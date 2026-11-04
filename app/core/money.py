from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_amount(value: str, scale: int = 100, *, allow_zero: bool = False) -> int:
    normalized = value.strip().replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("Summani raqam bilan kiriting.") from exc
    if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError("Summa noldan katta bo‘lishi kerak.")
    minor = (amount * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if minor > 10**15:
        raise ValueError("Kiritilgan summa juda katta.")
    return int(minor)


def format_money(minor: int, currency: str = "UZS", scale: int = 100) -> str:
    amount = Decimal(minor) / Decimal(scale)
    if amount == amount.to_integral_value():
        formatted = f"{int(amount):,}".replace(",", " ")
    else:
        formatted = f"{amount:,.2f}".replace(",", " ")
    return f"{formatted} {currency}"
