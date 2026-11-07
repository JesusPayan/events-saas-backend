
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from sqlalchemy import func, select

from app.extensions import db
from app.models.crm import Client
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation


@pytest.fixture
def reservation_scenario(flask_app, test_context):
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
        pytest.fail("API_BASE_URL debe apuntar al servidor local de pruebas")

    try:
        response = requests.get(
            f"{base_url}/health",
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(f"Servidor de pruebas no disponible: {exc}")

    tenant_id = test_context["tenant_id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    suffix = uuid4().hex[:12]

    with flask_app.app_context():
        try:
            client = Client(
                tenant_id=tenant_id,
                client_type="individual",
                first_name="Cliente",
                last_name="Concurrencia",
                status="active",
            )
            db.session.add(client)
            db.session.flush()

            starts_at = now + timedelta(days=7)
            ends_at = starts_at + timedelta(hours=6)

            events = [
                Event(
                    tenant_id=tenant_id,
                    client_id=client.id,
                    name=f"Concurrencia {suffix} {index}",
                    event_type="social",
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status="draft",
                )
                for index in (1, 2)
            ]

            db.session.add_all(events)
            db.session.flush()

            item = InventoryItem(
                tenant_id=tenant_id,
                sku=f"TEST-RES-{suffix}",
                name="Artículo concurrencia",
                item_type="product",
                quantity_total=1,
                quantity_unavailable=0,
                unit="piece",
                is_active=True,
            )

            db.session.add(item)
            db.session.flush()

            scenario = {
                "tenant_id": tenant_id,
                "event_ids": [event.id for event in events],
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
            return scenario

        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()


def test_no_overselling_under_concurrency(
    reservation_scenario,
    flask_app,
):
    scenario = reservation_scenario
    barrier = Barrier(2)

    def reserve(event_id):
        barrier.wait(timeout=10)

        response = requests.post(
            f"{scenario['base_url']}/events/"
            f"{event_id}/reservations",
            headers=scenario["headers"],
            json={
                "inventory_item_id": scenario["item_id"],
                "quantity": 1,
            },
            timeout=45,
        )

        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]

        return {
            "event_id": event_id,
            "status": response.status_code,
            "body": body,
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(reserve, scenario["event_ids"])
        )

    print("Resultados concurrentes:", results)

    statuses = sorted(
        result["status"] for result in results
    )

    assert statuses == [201, 409], results

    rejected = next(
        result["body"]
        for result in results
        if result["status"] == 409
    )

    assert isinstance(rejected, dict), rejected
    assert rejected.get("error") == "insufficient_inventory"

    with flask_app.app_context():
        try:
            reservations = db.session.scalars(
                select(InventoryReservation).where(
                    InventoryReservation.tenant_id
                    == scenario["tenant_id"],
                    InventoryReservation.inventory_item_id
                    == scenario["item_id"],
                    InventoryReservation.status == "reserved",
                )
            ).all()

            total_reserved = sum(
                reservation.quantity
                for reservation in reservations
            )

            assert len(reservations) == 1
            assert total_reserved == 1

            item = db.session.get(
                InventoryItem,
                scenario["item_id"],
            )

            assert item.quantity_total == 1
        finally:
            db.session.remove()
