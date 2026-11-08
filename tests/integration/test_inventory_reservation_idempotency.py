
"""INV-48-04: pruebas HTTP reales contra crm_events_test (puerto 5001)."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
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
from app.models.api_idempotency_key import ApiIdempotencyKey
from app.models.inventory_reservation_audit import InventoryReservationAudit
from sqlalchemy.exc import IntegrityError

@pytest.fixture
def idempotency_scenario(flask_app, test_context):
    base_url = os.getenv(
        "API_BASE_URL",
        "http://127.0.0.1:5001/api/v1",
    ).rstrip("/")

    parsed = urlsplit(base_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port != 5001
        or parsed.path != "/api/v1"
    ):
        pytest.fail(
            "API_BASE_URL debe apuntar a "
            "http://127.0.0.1:5001/api/v1"
        )

    try:
        response = requests.get(
            f"{base_url}/health",
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(
            f"Servidor de pruebas no disponible: {exc}"
        )

    tenant_id = test_context["tenant_id"]
    suffix = uuid4().hex[:12]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with flask_app.app_context():
        try:
            client = Client(
                tenant_id=tenant_id,
                client_type="individual",
                first_name="Cliente",
                last_name="Idempotencia",
                status="active",
            )

            db.session.add(client)
            db.session.flush()

            event = Event(
                tenant_id=tenant_id,
                client_id=client.id,
                name=f"Idempotencia {suffix}",
                event_type="social",
                starts_at=now + timedelta(days=7),
                ends_at=now + timedelta(
                    days=7,
                    hours=6,
                ),
                status="draft",
            )

            item = InventoryItem(
                tenant_id=tenant_id,
                sku=f"TEST-IDEM-{suffix}",
                name="Articulo idempotencia",
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


def post_reservation(scenario, key, quantity=2):
    return requests.post(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations",
        headers={
            **scenario["headers"],
            "Idempotency-Key": key,
        },
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": quantity,
        },
        timeout=45,
    )


def audit_rows(flask_app, scenario, reservation_id):
    with flask_app.app_context():
        try:
            rows = db.session.scalars(
                select(InventoryReservationAudit)
                .where(
                    InventoryReservationAudit.tenant_id
                    == scenario["tenant_id"],
                    InventoryReservationAudit.reservation_id
                    == reservation_id,
                )
                .order_by(InventoryReservationAudit.id)
            ).all()

            return [
                (
                    row.action,
                    row.previous_quantity,
                    row.new_quantity,
                    row.previous_status,
                    row.new_status,
                )
                for row in rows
            ]

        finally:
            db.session.remove()


def test_replay_create_same_status_body_and_single_audit(
    idempotency_scenario,
    flask_app,
):
    s = idempotency_scenario
    key = f"create-{uuid4().hex}"

    first = post_reservation(s, key)
    assert first.status_code == 201, first.text

    second = post_reservation(s, key)
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    reservation_id = first.json()["id"]

    assert [
        row[0]
        for row in audit_rows(
            flask_app,
            s,
            reservation_id,
        )
    ] == ["created"]

    with flask_app.app_context():
        try:
            reservations = db.session.scalars(
                select(InventoryReservation).where(
                    InventoryReservation.tenant_id
                    == s["tenant_id"],
                    InventoryReservation.event_id
                    == s["event_id"],
                    InventoryReservation.inventory_item_id
                    == s["item_id"],
                )
            ).all()

            assert len(reservations) == 1
            assert reservations[0].quantity == 2

        finally:
            db.session.remove()


def test_same_key_different_payload_is_conflict(
    idempotency_scenario,
    flask_app,
):
    s = idempotency_scenario
    key = f"conflict-{uuid4().hex}"

    first = post_reservation(s, key, 2)
    assert first.status_code == 201, first.text

    second = post_reservation(s, key, 3)
    assert second.status_code == 409, second.text

    assert (
        second.json()["error"]
        == "idempotency_key_conflict"
    )

    assert [
        row[0]
        for row in audit_rows(
            flask_app,
            s,
            first.json()["id"],
        )
    ] == ["created"]


def test_update_and_noop_audit(
    idempotency_scenario,
    flask_app,
):
    s = idempotency_scenario

    created = post_reservation(
        s,
        f"initial-{uuid4().hex}",
        2,
    )
    assert created.status_code == 201, created.text

    changed = post_reservation(
        s,
        f"update-{uuid4().hex}",
        3,
    )
    assert changed.status_code == 200, changed.text

    assert changed.json()["id"] == created.json()["id"]

    noop = post_reservation(
        s,
        f"noop-{uuid4().hex}",
        3,
    )
    assert noop.status_code == 200, noop.text

    assert [
        row[0]
        for row in audit_rows(
            flask_app,
            s,
            created.json()["id"],
        )
    ] == ["created", "updated"]


def test_cancel_replay_and_reactivation(
    idempotency_scenario,
    flask_app,
):
    s = idempotency_scenario

    created = post_reservation(
        s,
        f"initial-{uuid4().hex}",
        2,
    )
    assert created.status_code == 201, created.text

    reservation_id = created.json()["id"]

    url = (
        f"{s['base_url']}/events/"
        f"{s['event_id']}/reservations/"
        f"{reservation_id}/cancel"
    )

    key = f"cancel-{uuid4().hex}"

    headers = {
        **s["headers"],
        "Idempotency-Key": key,
    }

    first = requests.patch(
        url,
        headers=headers,
        timeout=45,
    )
    assert first.status_code == 200, first.text

    second = requests.patch(
        url,
        headers=headers,
        timeout=45,
    )
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    assert [
        row[0]
        for row in audit_rows(
            flask_app,
            s,
            reservation_id,
        )
    ] == ["created", "cancelled"]

    reactivated = post_reservation(
        s,
        f"reactivate-{uuid4().hex}",
        2,
    )
    assert reactivated.status_code == 200, reactivated.text

    assert [
        row[0]
        for row in audit_rows(
            flask_app,
            s,
            reservation_id,
        )
    ] == [
        "created",
        "cancelled",
        "reactivated",
    ]


def test_concurrent_same_key_one_effect(
    idempotency_scenario,
    flask_app,
):
    s = idempotency_scenario
    key = f"parallel-{uuid4().hex}"
    barrier = Barrier(2)

    def worker(_):
        barrier.wait(timeout=10)

        response = post_reservation(
            s,
            key,
            2,
        )

        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(worker, range(2))
        )

    assert [
        status
        for status, _ in results
    ] == [201, 201], results

    assert results[0][1] == results[1][1]

    reservation_id = results[0][1]["id"]

    assert [
        row[0]
        for row in audit_rows(
            flask_app,
            s,
            reservation_id,
        )
    ] == ["created"]

    with flask_app.app_context():
        try:
            rows = db.session.scalars(
                select(ApiIdempotencyKey).where(
                    ApiIdempotencyKey.tenant_id
                    == s["tenant_id"],
                    ApiIdempotencyKey.operation
                    == "reservation.upsert",
                    ApiIdempotencyKey.idempotency_key
                    == key,
                )
            ).all()

            assert len(rows) == 1
            assert rows[0].response_status == 201

        finally:
            db.session.remove()


def test_failed_validation_does_not_leave_idempotency_key(
    idempotency_scenario,
    flask_app,
):
    s = idempotency_scenario
    key = f"failed-{uuid4().hex}"

    rejected = post_reservation(
        s,
        key,
        11,
    )

    assert rejected.status_code == 409, rejected.text
    assert (
        rejected.json()["error"]
        == "insufficient_inventory"
    )

    with flask_app.app_context():
        try:
            record = db.session.scalar(
                select(ApiIdempotencyKey).where(
                    ApiIdempotencyKey.tenant_id
                    == s["tenant_id"],
                    ApiIdempotencyKey.operation
                    == "reservation.upsert",
                    ApiIdempotencyKey.idempotency_key
                    == key,
                )
            )

            assert record is None

        finally:
            db.session.remove()

    accepted = post_reservation(
        s,
        key,
        2,
    )

    assert accepted.status_code == 201, accepted.text

def test_audit_failure_rolls_back_reservation_and_idempotency(
    idempotency_scenario,
    flask_app,
):
    """
    INV-48-04: verificar atomicidad en MySQL.

    Una falla de integridad al insertar la auditoría
    debe revertir también la reservación y la clave
    de idempotencia de la misma transacción.

    Esta prueba opera directamente con SQLAlchemy.
    No inyecta fallos en el proceso HTTP de Flask.
    """
    scenario = idempotency_scenario

    tenant_id = scenario["tenant_id"]
    event_id = scenario["event_id"]
    item_id = scenario["item_id"]

    key = f"rollback-{uuid4().hex}"

    reservation_id = None

    with flask_app.app_context():
        try:
            # 1. Iniciar una transacción con una clave
            # de idempotencia nueva.
            idempotency_record = ApiIdempotencyKey(
                tenant_id=tenant_id,
                operation="reservation.upsert",
                idempotency_key=key,
                request_hash="a" * 64,
            )

            db.session.add(idempotency_record)
            db.session.flush()

            # 2. Crear la reservación dentro de
            # la misma transacción.
            reservation = InventoryReservation(
                tenant_id=tenant_id,
                event_id=event_id,
                inventory_item_id=item_id,
                quantity=2,
                status="reserved",
            )

            db.session.add(reservation)
            db.session.flush()

            reservation_id = reservation.id

            # 3. Provocar una falla real de integridad
            # utilizando un usuario inexistente.
            audit = InventoryReservationAudit(
                tenant_id=tenant_id,
                reservation_id=reservation_id,
                action="created",
                previous_quantity=None,
                new_quantity=2,
                previous_status=None,
                new_status="reserved",
                changed_by=999999999999999,
            )

            db.session.add(audit)

            # MySQL debe rechazar el registro porque
            # changed_by referencia users.id.
            with pytest.raises(IntegrityError):
                db.session.flush()

        finally:
            # 4. Revertir toda la transacción.
            db.session.rollback()
            db.session.remove()

    # 5. Verificar desde una sesión nueva que
    # ninguna de las escrituras quedó persistida.
    with flask_app.app_context():
        try:
            stored_key = db.session.scalar(
                select(ApiIdempotencyKey).where(
                    ApiIdempotencyKey.tenant_id == tenant_id,
                    ApiIdempotencyKey.operation
                    == "reservation.upsert",
                    ApiIdempotencyKey.idempotency_key == key,
                )
            )

            stored_reservation = db.session.scalar(
                select(InventoryReservation).where(
                    InventoryReservation.id == reservation_id,
                    InventoryReservation.tenant_id == tenant_id,
                )
            )

            stored_audits = db.session.scalars(
                select(InventoryReservationAudit).where(
                    InventoryReservationAudit.tenant_id
                    == tenant_id,
                    InventoryReservationAudit.reservation_id
                    == reservation_id,
                )
            ).all()

            assert stored_key is None, (
                "La clave de idempotencia quedó persistida "
                "después del rollback."
            )

            assert stored_reservation is None, (
                "La reservación quedó persistida "
                "después del rollback."
            )

            assert stored_audits == [], (
                "Se encontraron auditorías persistidas "
                "después del rollback."
            )

        finally:
            db.session.remove()
