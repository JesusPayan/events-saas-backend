
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY = Decimal("0.01")
ZERO = Decimal("0.00")
ONE = Decimal("1.00")


class QuoteCalculationError(ValueError):
    pass


def to_decimal(value, field_name):
    if isinstance(value, bool) or value is None:
        raise QuoteCalculationError(
            f"{field_name} debe ser un número válido."
        )

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteCalculationError(
            f"{field_name} debe ser un número válido."
        )

    if not result.is_finite():
        raise QuoteCalculationError(
            f"{field_name} debe ser un número finito."
        )

    return result


def money(value):
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def calculate_item(item):
    quantity = to_decimal(
        item.get("quantity"), "quantity"
    )
    unit_price = to_decimal(
        item.get("unit_price"), "unit_price"
    )
    discount = to_decimal(
        item.get("discount_amount", "0"),
        "discount_amount"
    )
    tax_rate = to_decimal(
        item.get("tax_rate", "0"),
        "tax_rate"
    )

    if quantity <= 0:
        raise QuoteCalculationError(
            "La cantidad debe ser mayor que cero."
        )

    if quantity.as_tuple().exponent < -2:
        raise QuoteCalculationError(
            "La cantidad admite máximo 2 decimales."
        )

    if unit_price < 0 or discount < 0:
        raise QuoteCalculationError(
            "El precio y descuento no pueden ser negativos."
        )

    if tax_rate < 0 or tax_rate > ONE:
        raise QuoteCalculationError(
            "La tasa de impuesto debe estar entre 0 y 1."
        )

    subtotal = money(quantity * unit_price)

    if discount != money(discount):
        raise QuoteCalculationError(
            "El descuento admite máximo 2 decimales."
        )

    if discount > subtotal:
        raise QuoteCalculationError(
            "El descuento no puede superar el subtotal."
        )

    taxable_amount = subtotal - discount
    tax_amount = money(taxable_amount * tax_rate)
    total = money(taxable_amount + tax_amount)

    return {
        "quantity": quantity,
        "unit_price": money(unit_price),
        "discount_amount": discount,
        "tax_rate": tax_rate,
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
    }


def calculate_quote(items):
    if not items:
        raise QuoteCalculationError(
            "La cotización debe contener al menos un concepto."
        )

    calculated_items = [
        calculate_item(item) for item in items
    ]

    subtotal = money(sum(
        (item["subtotal"] for item in calculated_items),
        ZERO
    ))

    discount_total = money(sum(
        (item["discount_amount"] for item in calculated_items),
        ZERO
    ))

    tax_total = money(sum(
        (item["tax_amount"] for item in calculated_items),
        ZERO
    ))

    total = money(
        subtotal - discount_total + tax_total
    )

    return {
        "items": calculated_items,
        "subtotal": subtotal,
        "discount_total": discount_total,
        "tax_total": tax_total,
        "total": total,
    }
