
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.contract_payment_service import (
    PaymentError,
    parse_amount,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2000", Decimal("2000.00")),
        ("2000.50", Decimal("2000.50")),
        (2000, Decimal("2000.00")),
        (Decimal("10.25"), Decimal("10.25")),
        ("0.01", Decimal("0.01")),
    ],
)
def test_parse_amount_valid(value, expected):
    assert parse_amount(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -1,
        "-100",
        "0.001",
        "10.999",
        "abc",
        "",
        "NaN",
        "Infinity",
        "9999999999999.99",
        10.5,
    ],
)
def test_parse_amount_invalid(value):
    with pytest.raises(PaymentError) as exc:
        parse_amount(value)

    assert exc.value.code == "invalid_amount"


def test_balance_uses_only_confirmed_payments():
    from app.services.contract_payment_service import get_balance

    contract = SimpleNamespace(
        id=1,
        tenant_id=1,
        total=Decimal("10000.00"),
        currency="MXN",
    )

    with (
        patch(
            "app.services.contract_payment_service.db.session.scalar",
            return_value=contract,
        ),
        patch(
            "app.services.contract_payment_service.confirmed_total",
            return_value=Decimal("2000.00"),
        ),
    ):
        result = get_balance(tenant_id=1, contract_id=1)

    assert result == {
        "contract_id": 1,
        "currency": "MXN",
        "total": "10000.00",
        "paid": "2000.00",
        "balance": "8000.00",
    }


def test_balance_rejects_missing_contract():
    from app.services.contract_payment_service import get_balance

    with patch(
        "app.services.contract_payment_service.db.session.scalar",
        return_value=None,
    ):
        with pytest.raises(PaymentError) as exc:
            get_balance(tenant_id=1, contract_id=999)

    assert exc.value.code == "contract_not_found"
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "invalid_value",
    [None, 123, True, [], {}, ""],
)
def test_invalid_payment_type(invalid_value):
    from app.services.contract_payment_service import register_payment

    with pytest.raises(PaymentError) as exc:
        register_payment(
            tenant_id=1,
            contract_id=1,
            user_id=1,
            amount="100.00",
            payment_type=invalid_value,
            payment_method="cash",
        )

    assert exc.value.code == "invalid_payment_type"


@pytest.mark.parametrize(
    "invalid_value",
    [None, 123, True, [], {}, ""],
)
def test_invalid_payment_method(invalid_value):
    from app.services.contract_payment_service import register_payment

    with pytest.raises(PaymentError) as exc:
        register_payment(
            tenant_id=1,
            contract_id=1,
            user_id=1,
            amount="100.00",
            payment_type="advance",
            payment_method=invalid_value,
        )

    assert exc.value.code == "invalid_payment_method"
