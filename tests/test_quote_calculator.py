
import pytest

from app.services.quote_calculator import (
    QuoteCalculationError,
    calculate_item,
    calculate_quote,
)


def test_calculate_quote():
    result = calculate_quote([
        {
            "quantity": 10,
            "unit_price": "150.00",
            "discount_amount": "0.00",
            "tax_rate": "0.16",
        },
        {
            "quantity": 1,
            "unit_price": "800.00",
            "discount_amount": "0.00",
            "tax_rate": "0.16",
        },
    ])

    assert str(result["subtotal"]) == "2300.00"
    assert str(result["tax_total"]) == "368.00"
    assert str(result["total"]) == "2668.00"


def test_discount():
    result = calculate_item({
        "quantity": 2,
        "unit_price": "500.00",
        "discount_amount": "100.00",
        "tax_rate": "0.16",
    })

    assert str(result["subtotal"]) == "1000.00"
    assert str(result["tax_amount"]) == "144.00"
    assert str(result["total"]) == "1044.00"


def test_invalid_discount():
    with pytest.raises(QuoteCalculationError):
        calculate_item({
            "quantity": 1,
            "unit_price": "100.00",
            "discount_amount": "150.00",
            "tax_rate": "0.16",
        })


def test_invalid_quantity():
    with pytest.raises(QuoteCalculationError):
        calculate_item({
            "quantity": 0,
            "unit_price": "100.00",
            "tax_rate": "0.16",
        })
