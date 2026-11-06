
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import requests
from sqlalchemy import func, select

from app.extensions import db
from app.models.crm import Client
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation
from app.models.inventory_movement import InventoryMovement
from app.models.inventory_incident import InventoryIncident
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_reconciliation_audit import (
    InventoryReconciliationAudit,
)


def create_reconciliation_scenario(context):
    tenant_id = context["tenant_id"]
    user_id = context["user_id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        # 1. Cliente
        client = Client(
            tenant_id=tenant_id,
            client_type="individual",
            first_name="Cliente",
            last_name="Prueba Concurrencia",
            email=f"test-{uuid4().hex[:12]}@example.com",
            status="active",
        )

        db.session.add(client)
        db.session.flush()

        # 2. Evento
        event = Event(
            tenant_id=tenant_id,
            client_id=client.id,
            name="Evento prueba concurrencia",
            event_type="social",
            starts_at=now + timedelta(days=7),
            ends_at=now + timedelta(days=7, hours=6),
            status="draft",
        )

        db.session.add(event)
        db.session.flush()

        # 3. Artículo
        item = InventoryItem(
            tenant_id=tenant_id,
            sku=f"TEST-CONC-{uuid4().hex[:12]}",
            name="Artículo prueba concurrencia",
            item_type="product",
            quantity_total=10,
            quantity_unavailable=0,
            unit="piece",
            replacement_cost=Decimal("150.00"),
            is_active=True,
        )

        db.session.add(item)
        db.session.flush()

        # 4. Reservación
        reservation = InventoryReservation(
            tenant_id=tenant_id,
            event_id=event.id,
            inventory_item_id=item.id,
            quantity=8,
            status="reserved",
        )

        db.session.add(reservation)
        db.session.flush()

        # 5. Movimiento de despacho
        movement = InventoryMovement(
            tenant_id=tenant_id,
            inventory_item_id=item.id,
            reservation_id=reservation.id,
            movement_type="dispatch",
            quantity=8,
            created_by=user_id,
            notes="Despacho de prueba",
        )

        # 6. Incidencia por pérdida
        incident = InventoryIncident(
            tenant_id=tenant_id,
            reservation_id=reservation.id,
            inventory_item_id=item.id,
            incident_type="lost",
            quantity=3,
            description="Pérdida simulada",
            status="reported",
            unit_cost=Decimal("150.00"),
            reported_by=user_id,
        )

        db.session.add_all([movement, incident])
        db.session.flush()

        result = {
            "tenant_id": tenant_id,
            "client_id": client.id,
            "event_id": event.id,
            "item_id": item.id,
            "reservation_id": reservation.id,
            "incident_id": incident.id,
            "initial_quantity_total": 10,
            "loss_quantity": 3,
        }

        db.session.commit()
        return result

    except Exception:
        db.session.rollback()
        raise


def test_create_reconciliation_scenario(
    test_context,
    flask_app,
):
    with flask_app.app_context():
        scenario = create_reconciliation_scenario(
            test_context
        )

        incident = db.session.get(
            InventoryIncident,
            scenario["incident_id"],
        )

        assert incident is not None
        assert incident.status == "reported"
        assert incident.quantity == 3
        assert scenario["item_id"] is not None

        db.session.remove()


def test_only_one_concurrent_reconciliation(
    reconciliation_scenario,
    flask_app,
):
    scenario = reconciliation_scenario

    # Sincroniza el inicio de los dos workers.
    barrier = Barrier(2)

    def reconcile(worker):
        barrier.wait(timeout=10)

        response = requests.post(
            scenario["url"],
            headers=scenario["headers"],
            json={
                "accept_deficit": True,
            },
            timeout=45,
        )

        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]

        return {
            "worker": worker,
            "status": response.status_code,
            "body": body,
        }

    # 1. Ejecutar dos solicitudes concurrentes
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(reconcile, (1, 2))
        )

    print("Resultados:", results)

    statuses = sorted(
        result["status"]
        for result in results
    )

    assert statuses == [200, 409], results

    # 2. Verificar que la segunda conciliación
    # haya sido rechazada.
    rejected = next(
        result["body"]
        for result in results
        if result["status"] == 409
    )

    assert isinstance(rejected, dict), rejected

    assert rejected.get("error") in {
        "incident_already_reconciled",
        "incident_not_reconcilable",
        "incident_already_adjusted",
    }, rejected

    # 3. Verificar integridad directamente en MySQL
    with flask_app.app_context():
        tenant_id = scenario["tenant_id"]
        incident_id = scenario["incident_id"]

        def count(model):
            return db.session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.tenant_id == tenant_id,
                    model.incident_id == incident_id,
                )
            )

        counts = {
            "adjustments": count(InventoryAdjustment),
            "charges": count(InventoryIncidentCharge),
            "audits": count(InventoryReconciliationAudit),
        }

        item = db.session.get(
            InventoryItem,
            scenario["item_id"],
        )

        incident = db.session.get(
            InventoryIncident,
            incident_id,
        )

        print(
            "Registros:", counts,
            "Inventario:", item.quantity_total,
            "Estado:", incident.status,
        )

        assert counts == {
            "adjustments": 1,
            "charges": 1,
            "audits": 1,
        }

        # Inventario: 10 - 3 = 7
        assert item.quantity_total == (
            scenario["initial_quantity_total"]
            - scenario["loss_quantity"]
        )

        assert item.quantity_unavailable == 0
        assert incident.status == "resolved"

        db.session.remove()
