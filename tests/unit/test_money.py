import pytest

from app.core.money import format_money, parse_amount


def test_parse_integer_amount():
    assert parse_amount("50 000", 100) == 5_000_000


def test_parse_decimal_amount():
    assert parse_amount("12,50", 100) == 1250


def test_parse_rejects_negative_and_zero():
    with pytest.raises(ValueError):
        parse_amount("-1", 100)
    with pytest.raises(ValueError):
        parse_amount("0", 100)


def test_money_format():
    assert format_money(5_000_000, "UZS", 100) == "50 000 UZS"
    assert format_money(1250, "UZS", 100) == "12.50 UZS"
