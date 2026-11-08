
import requests
import pytest

from test_inventory_full_lifecycle import lifecycle_scenario

from test_inventory_tenant_isolation import (
    restricted_inventory_user,
    two_tenant_inventory_scenario,
    unauthorized_tenant,
)
from app.extensions import db
from app.models.inventory_movement import InventoryMovement
REPORT_PATH = "/inventory/reports/movements"

from datetime import datetime, timedelta, timezone


def test_movement_report_filters_by_movement_date(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    reservation = requests.post(
        f"{s['base_url']}/events/{s['event_id']}/reservations",
        headers=s["headers"],
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 3,
        },
        timeout=45,
    )

    assert reservation.status_code == 201, reservation.text

    movement = requests.post(
        f"{s['base_url']}/inventory/movements/dispatch",
        headers=s["headers"],
        json={
            "reservation_id": reservation.json()["id"],
            "quantity": 3,
        },
        timeout=45,
    )

    assert movement.status_code == 201, movement.text

    now = datetime.now(timezone.utc)

    # Intervalo amplio que incluye el movimiento reciente.
    response = get_report(
        s,
        event_id=s["event_id"],
        date_from=(now - timedelta(days=1)).isoformat(),
        date_to=(now + timedelta(days=1)).isoformat(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["summary"]["quantity_dispatched"] == 3

    # Intervalo pasado que excluye el movimiento.
    response = get_report(
        s,
        event_id=s["event_id"],
        date_from=(now - timedelta(days=10)).isoformat(),
        date_to=(now - timedelta(days=5)).isoformat(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json()["items"] == []



def test_movement_report_isolates_foreign_tenant_movements(
    two_tenant_inventory_scenario,
    flask_app,
    test_context,
):
    s = two_tenant_inventory_scenario

    # Crear movimiento directamente en tenant B.
    with flask_app.app_context():
        try:
            movement = InventoryMovement(
                tenant_id=s["tenant_b_id"],
                inventory_item_id=s["item_b_id"],
                reservation_id=s["reservation_b_id"],
                movement_type="dispatch",
                quantity=3,
                created_by=test_context["user_id"],
            )

            db.session.add(movement)
            db.session.commit()
            movement_id = movement.id

        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()

    # Consultar el reporte autenticado en tenant A.
    response = requests.get(
        f"{s['base_url']}{REPORT_PATH}",
        headers=s["headers_a"],
        params={
            "item_id": s["item_b_id"],
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 0
    assert data["items"] == []
    assert data["summary"]["quantity_dispatched"] == 0

    # Verificar que el movimiento de B sigue existiendo.
    with flask_app.app_context():
        try:
            saved = db.session.get(
                InventoryMovement,
                movement_id,
            )

            assert saved is not None
            assert saved.tenant_id == s["tenant_b_id"]
            assert saved.quantity == 3

        finally:
            db.session.remove()


def test_movement_report_rejects_unauthorized_tenant(
    lifecycle_scenario,
    unauthorized_tenant,
    test_context,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}{REPORT_PATH}",
        headers={
            "Authorization": f"Bearer {test_context['token']}",
            "X-Tenant-ID": str(unauthorized_tenant),
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"

def test_movement_report_full_dispatch_return_lifecycle(
    lifecycle_scenario,
):
    s = lifecycle_scenario
    base_url = s["base_url"]
    headers = s["headers"]

    # 1. Crear reservación de cuatro unidades.
    reservation_response = requests.post(
        f"{base_url}/events/{s['event_id']}/reservations",
        headers=headers,
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 4,
        },
        timeout=45,
    )

    assert reservation_response.status_code == 201, (
        reservation_response.text
    )

    reservation_id = reservation_response.json()["id"]

    def register_movement(movement_type, quantity):
        response = requests.post(
            f"{base_url}/inventory/movements/{movement_type}",
            headers=headers,
            json={
                "reservation_id": reservation_id,
                "quantity": quantity,
            },
            timeout=45,
        )

        assert response.status_code == 201, response.text
        return response.json()

    def check_report(
        expected_total,
        dispatched,
        returned,
        outstanding,
    ):
        response = get_report(
            s,
            event_id=s["event_id"],
            item_id=s["item_id"],
        )

        assert response.status_code == 200, response.text

        data = response.json()
        summary = data["summary"]

        assert data["total"] == expected_total
        assert len(data["items"]) == expected_total

        assert summary["quantity_dispatched"] == dispatched
        assert summary["quantity_returned"] == returned
        assert summary["quantity_outstanding"] == outstanding

        return data

    # 2. Antes de registrar movimientos.
    check_report(
        expected_total=0,
        dispatched=0,
        returned=0,
        outstanding=0,
    )

    # 3. Entregar cuatro unidades.
    register_movement("dispatch", 4)

    check_report(
        expected_total=1,
        dispatched=4,
        returned=0,
        outstanding=4,
    )

    # 4. Devolver dos unidades.
    register_movement("return", 2)

    check_report(
        expected_total=2,
        dispatched=4,
        returned=2,
        outstanding=2,
    )

    # 5. Devolver las dos restantes.
    register_movement("return", 2)

    data = check_report(
        expected_total=3,
        dispatched=4,
        returned=4,
        outstanding=0,
    )

    assert sorted(
        item["movement_type"] for item in data["items"]
    ) == ["dispatch", "return", "return"]

    assert sorted(
        item["quantity"] for item in data["items"]
    ) == [2, 2, 4]

def test_movement_report_pagination_and_filters(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    reservation = requests.post(
        f"{s['base_url']}/events/{s['event_id']}/reservations",
        headers=s["headers"],
        json={
            "inventory_item_id": s["item_id"],
            "quantity": 4,
        },
        timeout=45,
    )

    assert reservation.status_code == 201, reservation.text
    reservation_id = reservation.json()["id"]

    for movement_type, quantity in [
        ("dispatch", 4),
        ("return", 2),
    ]:
        response = requests.post(
            f"{s['base_url']}/inventory/movements/{movement_type}",
            headers=s["headers"],
            json={
                "reservation_id": reservation_id,
                "quantity": quantity,
            },
            timeout=45,
        )

        assert response.status_code == 201, response.text

    # Solo un registro por página.
    response = get_report(
        s,
        event_id=s["event_id"],
        per_page=1,
        page=1,
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["total"] == 2
    assert data["pages"] == 2
    assert len(data["items"]) == 1

    # El resumen incluye ambas páginas.
    assert data["summary"]["quantity_dispatched"] == 4
    assert data["summary"]["quantity_returned"] == 2
    assert data["summary"]["quantity_outstanding"] == 2

    # Filtrar exclusivamente entregas.
    response = get_report(
        s,
        event_id=s["event_id"],
        movement_type="dispatch",
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["total"] == 1
    assert data["items"][0]["movement_type"] == "dispatch"
    assert data["summary"]["quantity_dispatched"] == 4
    assert data["summary"]["quantity_returned"] == 0


def test_movement_report_requires_inventory_read(
    lifecycle_scenario,
    restricted_inventory_user,
):
    s = lifecycle_scenario
    user = restricted_inventory_user

    response = requests.get(
        f"{s['base_url']}{REPORT_PATH}",
        headers={
            "Authorization": f"Bearer {user['token']}",
            "X-Tenant-ID": str(user["tenant_id"]),
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"


def get_report(scenario, **params):
    response = requests.get(
        f"{scenario['base_url']}{REPORT_PATH}",
        headers=scenario["headers"],
        params=params,
        timeout=45,
    )
    return response


def test_movement_report_without_movements(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    response = get_report(
        s,
        event_id=s["event_id"],
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 0
    assert data["items"] == []
    assert data["summary"]["quantity_dispatched"] == 0
    assert data["summary"]["quantity_returned"] == 0
    assert data["summary"]["quantity_outstanding"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"per_page": 101},
        {"event_id": -1},
        {"item_id": "abc"},
        {"movement_type": "invalid"},
        {"date_from": "fecha-invalida"},
        {
            "date_from": "2026-11-20T20:00:00Z",
            "date_to": "2026-11-20T10:00:00Z",
        },
    ],
)
def test_movement_report_invalid_parameters(
    lifecycle_scenario,
    params,
):
    response = get_report(
        lifecycle_scenario,
        **params,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"] == "validation_error"


def test_movement_report_requires_authentication(
    lifecycle_scenario,
):
    s = lifecycle_scenario

    response = requests.get(
        f"{s['base_url']}{REPORT_PATH}",
        headers={
            "X-Tenant-ID": str(s["tenant_id"]),
        },
        timeout=45,
    )

    assert response.status_code == 401, response.text
