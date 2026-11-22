
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from sqlalchemy import select

from app.extensions import db
from app.models.crm import Client
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation


@pytest.fixture
def lifecycle_scenario(flask_app, test_context):
    base_url = os.getenv(
        "API_BASE_URL",
        "http://127.0.0.1:5001/api/v1",
    ).rstrip("/")

    parsed = urlsplit(base_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port not in (5001, 5002)
        or parsed.path != "/api/v1"
    ):
        pytest.fail(
            "API_BASE_URL debe apuntar al servidor local "
            "de pruebas en el puerto 5001"
        )

    try:
        response = requests.get(
            f"{base_url}/health",
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(f"Servidor no disponible: {exc}")

    tenant_id = test_context["tenant_id"]
    suffix = uuid4().hex[:12]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    starts_at = now + timedelta(days=7)
    ends_at = starts_at + timedelta(hours=6)

    with flask_app.app_context():
        try:
            client = Client(
                tenant_id=tenant_id,
                client_type="individual",
                first_name="Cliente",
                last_name="Ciclo Completo",
                status="active",
            )

            db.session.add(client)
            db.session.flush()

            event = Event(
                tenant_id=tenant_id,
                client_id=client.id,
                name=f"Ciclo completo {suffix}",
                event_type="social",
                starts_at=starts_at,
                ends_at=ends_at,
                status="draft",
            )

            item = InventoryItem(
                tenant_id=tenant_id,
                sku=f"TEST-LIFE-{suffix}",
                name="Articulo ciclo completo",
                item_type="product",
                quantity_total=10,
                quantity_unavailable=0,
                unit="piece",
                is_active=True,
            )

            db.session.add_all([event, item])
            db.session.flush()

            result = {
                "tenant_id": tenant_id,
                "event_id": event.id,
                "item_id": item.id,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "base_url": base_url,
                "headers": {
                    "Authorization": (
                        f"Bearer {test_context['token']}"
                    ),
                    "X-Tenant-ID": str(tenant_id),
                    "Content-Type": "application/json",
                },
            }

            db.session.commit()
            return result

        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()


def test_inventory_full_lifecycle(lifecycle_scenario, flask_app):
    s = lifecycle_scenario
    headers = s["headers"]

    # 1. Crear una reserva de cinco unidades.
    reserve = requests.post(
        f"{s['base_url']}/events/"
        f"{s['event_id']}/reservations",
        headers={
            **headers,
            "Idempotency-Key": f"life-{uuid4().hex}",
        },
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 5,
        },
        timeout=45,
    )

    assert reserve.status_code == 201, reserve.text
    reservation_id = reserve.json()["id"]

    # 2. Consultar disponibilidad.
    availability = requests.get(
        f"{s['base_url']}/inventory/availability",
        headers=headers,
        params={
            "item_id": s["item_id"],
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        },
        timeout=45,
    )

    assert availability.status_code == 200, availability.text
    assert availability.json()["quantity_available"] == 5

    movement_url = (
        f"{s['base_url']}/inventory/movements"
    )

    # 3. Entregar cinco unidades.
    dispatch = requests.post(
        f"{movement_url}/dispatch",
        headers=headers,
        json={
            "reservation_id": reservation_id,
            "quantity": 5,
            "notes": "Entrega inicial E2E",
        },
        timeout=45,
    )

    assert dispatch.status_code == 201, dispatch.text
    assert dispatch.json()["summary"]["quantity_dispatched"] == 5
    assert dispatch.json()["summary"]["quantity_outstanding"] == 5

    # 4. Devolver dos unidades.
    partial_return = requests.post(
        f"{movement_url}/return",
        headers=headers,
        json={
            "reservation_id": reservation_id,
            "quantity": 2,
            "notes": "Devolucion parcial E2E",
        },
        timeout=45,
    )

    assert partial_return.status_code == 201, partial_return.text
    assert partial_return.json()["summary"]["quantity_returned"] == 2
    assert partial_return.json()["summary"]["quantity_outstanding"] == 3

    # 5. Devolver las tres unidades restantes.
    final_return = requests.post(
        f"{movement_url}/return",
        headers=headers,
        json={
            "reservation_id": reservation_id,
            "quantity": 3,
            "notes": "Devolucion final E2E",
        },
        timeout=45,
    )

    assert final_return.status_code == 201, final_return.text

    summary = final_return.json()["summary"]

    assert summary["quantity_dispatched"] == 5
    assert summary["quantity_returned"] == 5
    assert summary["quantity_outstanding"] == 0
    assert summary["quantity_administrative_outstanding"] == 0
    assert summary["is_fully_reconciled"] is True

    # 6. Consultar historial de movimientos.
    movements = requests.get(
        movement_url,
        headers=headers,
        params={"reservation_id": reservation_id},
        timeout=45,
    )

    assert movements.status_code == 200, movements.text

    body = movements.json()

    assert len(body["items"]) == 3

    movement_types = [
        movement["movement_type"]
        for movement in body["items"]
    ]

    assert movement_types.count("dispatch") == 1
    assert movement_types.count("return") == 2

    # 7. Cancelar la reserva reconciliada.
    cancellation = requests.patch(
        f"{s['base_url']}/events/"
        f"{s['event_id']}/reservations/"
        f"{reservation_id}/cancel",
        headers={
            **headers,
            "Idempotency-Key": f"cancel-{uuid4().hex}",
        },
        timeout=45,
    )

    assert cancellation.status_code == 200, cancellation.text
    assert cancellation.json()["status"] == "cancelled"

    # 8. Confirmar estado persistido en MySQL.
    with flask_app.app_context():
        try:
            reservation = db.session.scalar(
                select(InventoryReservation).where(
                    InventoryReservation.id == reservation_id,
                    InventoryReservation.tenant_id == s["tenant_id"],
                )
            )

            assert reservation is not None
            assert reservation.status == "cancelled"
            assert reservation.quantity == 5

        finally:
            db.session.remove()
