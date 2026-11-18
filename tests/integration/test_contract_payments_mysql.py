
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models.crm import Client
from app.models.event import Event
from app.models.quote import Quote
from app.models.contract import Contract
from app.models.identity import User


@pytest.fixture
def mysql_payment_case():
    app = create_app({"TESTING": True})

    with app.app_context():
        database_name = db.session.execute(
            text("SELECT DATABASE()")
        ).scalar()

        if database_name != "crm_events_test":
            pytest.fail(
                "Prueba bloqueada: la conexión apunta a "
                f"{database_name!r}, no a crm_events_test."
            )

        suffix = uuid4().hex[:12]
        email = f"payment-{suffix}@example.test"
        slug = f"payment-{suffix}"

        http = app.test_client()

        response = http.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "payment-test-password-123",
                "company_name": f"Payment Test {suffix}",
                "slug": slug,
            },
        )
        assert response.status_code == 201, response.get_json()

        tenant_id = response.json["tenant_id"]

        login = http.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": "payment-test-password-123",
            },
        )
        assert login.status_code == 200, login.get_json()

        headers = {
            "Authorization": f"Bearer {login.json['access_token']}",
            "X-Tenant-ID": str(tenant_id),
        }

        user = db.session.query(User).filter_by(email=email).one()

        # Crear cliente y evento usando los endpoints existentes.
        customer = http.post(
            "/api/v1/clients",
            headers=headers,
            json={
                "client_type": "individual",
                "first_name": "Cliente",
                "last_name": "Prueba Pagos",
            },
        )
        assert customer.status_code == 201, customer.get_json()

        client_id = customer.json["id"]

        event_response = http.post(
            "/api/v1/events",
            headers=headers,
            json={
                "client_id": client_id,
                "name": "Evento de integración financiera",
                "event_type": "wedding",
                "starts_at": "2027-02-01T12:00:00Z",
                "ends_at": "2027-02-01T20:00:00Z",
            },
        )
        assert event_response.status_code == 201, (
            event_response.get_json()
        )

        event_id = event_response.json["id"]

        quote = Quote(
            tenant_id=tenant_id,
            event_id=event_id,
            client_id=client_id,
            quote_number=f"Q-{suffix}",
            status="accepted",
            currency="MXN",
            subtotal=Decimal("10000.00"),
            discount_total=Decimal("0.00"),
            tax_total=Decimal("0.00"),
            total=Decimal("10000.00"),
            created_by=user.id,
        )
        db.session.add(quote)
        db.session.flush()

        contract = Contract(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_id=event_id,
            client_id=client_id,
            contract_number=f"C-{suffix}",
            status="active",
            currency="MXN",
            subtotal=Decimal("10000.00"),
            discount_total=Decimal("0.00"),
            tax_total=Decimal("0.00"),
            total=Decimal("10000.00"),
            created_by=user.id,
        )
        db.session.add(contract)
        db.session.commit()

        yield {
            "http": http,
            "headers": headers,
            "tenant_id": tenant_id,
            "contract_id": contract.id,
            "quote_id": quote.id,
            "event_id": event_id,
            "client_id": client_id,
            "user_id": user.id,
        }

        # La limpieza integral se implementará en el fixture
        # definitivo antes de habilitar su ejecución normal.


def test_payment_full_lifecycle(mysql_payment_case):
    case = mysql_payment_case
    http = case["http"]
    headers = case["headers"]
    contract_id = case["contract_id"]

    base = f"/api/v1/contracts/{contract_id}/payments"

    created = http.post(
        base,
        headers=headers,
        json={
            "amount": "2000.00",
            "payment_type": "advance",
            "payment_method": "bank_transfer",
            "reference": f"ADV-{uuid4().hex[:12]}",
        },
    )

    assert created.status_code == 201, created.get_json()
    assert created.json["status"] == "pending"

    payment_id = created.json["id"]

    balance = http.get(f"{base}/balance", headers=headers)
    assert balance.status_code == 200
    assert Decimal(balance.json["paid"]) == Decimal("0.00")

    confirmed = http.patch(
        f"{base}/{payment_id}/confirm",
        headers=headers,
        json={},
    )

    assert confirmed.status_code == 200, confirmed.get_json()
    assert confirmed.json["status"] == "confirmed"

    balance = http.get(f"{base}/balance", headers=headers)

    assert balance.status_code == 200
    assert Decimal(balance.json["paid"]) == Decimal("2000.00")
    assert Decimal(balance.json["balance"]) == Decimal("8000.00")

    repeated = http.patch(
        f"{base}/{payment_id}/confirm",
        headers=headers,
        json={},
    )
    assert repeated.status_code == 409

    audits = http.get(
        f"{base}/{payment_id}/audit",
        headers=headers,
    )
    assert audits.status_code == 200

    actions = [
        item["action"]
        for item in audits.json["items"]
    ]

    assert actions == ["created", "confirmed"]
