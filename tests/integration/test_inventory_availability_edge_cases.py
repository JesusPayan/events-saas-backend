
import requests
import pytest

from test_inventory_full_lifecycle import lifecycle_scenario


@pytest.mark.parametrize(
    "movement_type,quantity,expected_error",
    [
        ("dispatch", 6, "dispatch_exceeds_reservation"),
        ("return", 1, "nothing_to_return"),
    ],
)
def test_invalid_movements(
    lifecycle_scenario,
    movement_type,
    quantity,
    expected_error,
):
    scenario = lifecycle_scenario

    # Crear reserva de cinco unidades.
    response = requests.post(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 5,
        },
        timeout=45,
    )

    assert response.status_code == 201, response.text

    reservation_id = response.json()["id"]

    # Intentar movimiento inválido.
    response = requests.post(
        f"{scenario['base_url']}/inventory/movements/"
        f"{movement_type}",
        headers=scenario["headers"],
        json={
            "reservation_id": reservation_id,
            "quantity": quantity,
        },
        timeout=45,
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"] == expected_error


def test_return_exceeds_outstanding(lifecycle_scenario):
    scenario = lifecycle_scenario

    reservation = requests.post(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 5,
        },
        timeout=45,
    )

    assert reservation.status_code == 201, reservation.text
    reservation_id = reservation.json()["id"]

    # Entregar tres unidades.
    dispatch = requests.post(
        f"{scenario['base_url']}/inventory/movements/dispatch",
        headers=scenario["headers"],
        json={
            "reservation_id": reservation_id,
            "quantity": 3,
        },
        timeout=45,
    )

    assert dispatch.status_code == 201, dispatch.text

    # Intentar devolver cuatro.
    response = requests.post(
        f"{scenario['base_url']}/inventory/movements/return",
        headers=scenario["headers"],
        json={
            "reservation_id": reservation_id,
            "quantity": 4,
        },
        timeout=45,
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"] == "return_exceeds_outstanding"


def test_dispatch_after_cancellation(lifecycle_scenario):
    scenario = lifecycle_scenario

    reservation = requests.post(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 5,
        },
        timeout=45,
    )

    assert reservation.status_code == 201, reservation.text
    reservation_id = reservation.json()["id"]

    cancellation = requests.patch(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations/"
        f"{reservation_id}/cancel",
        headers=scenario["headers"],
        timeout=45,
    )

    assert cancellation.status_code == 200, cancellation.text

    response = requests.post(
        f"{scenario['base_url']}/inventory/movements/dispatch",
        headers=scenario["headers"],
        json={
            "reservation_id": reservation_id,
            "quantity": 1,
        },
        timeout=45,
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"] == "reservation_not_active"


def test_cannot_cancel_with_outstanding_items(lifecycle_scenario):
    scenario = lifecycle_scenario
    base_url = scenario["base_url"]
    event_id = scenario["event_id"]
    headers = scenario["headers"]

    # Crear reservación.
    reservation_response = requests.post(
        f"{base_url}/events/{event_id}/reservations",
        headers=headers,
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 5,
        },
        timeout=45,
    )

    assert reservation_response.status_code == 201, (
        reservation_response.text
    )

    reservation_id = reservation_response.json()["id"]

    # Entregar tres unidades.
    dispatch_response = requests.post(
        f"{base_url}/inventory/movements/dispatch",
        headers=headers,
        json={
            "reservation_id": reservation_id,
            "quantity": 3,
        },
        timeout=45,
    )

    assert dispatch_response.status_code == 201, (
        dispatch_response.text
    )

    # Intentar cancelar con tres unidades pendientes.
    cancel_response = requests.patch(
        f"{base_url}/events/{event_id}/reservations/"
        f"{reservation_id}/cancel",
        headers=headers,
        timeout=45,
    )

    assert cancel_response.status_code == 409, (
        cancel_response.text
    )
    assert cancel_response.json()["error"] == "pending_returns"

    # Confirmar que los movimientos permanecen intactos.
    movements_response = requests.get(
        f"{base_url}/inventory/movements",
        headers=headers,
        params={"reservation_id": reservation_id},
        timeout=45,
    )

    assert movements_response.status_code == 200

    summary = movements_response.json()["summary"]

    assert summary["quantity_dispatched"] == 3
    assert summary["quantity_returned"] == 0
    assert summary["quantity_outstanding"] == 3


from datetime import timedelta
from uuid import uuid4

from app.extensions import db
from app.models.event import Event



def create_second_event(scenario, flask_app, starts_at, ends_at):
    with flask_app.app_context():
        try:
            # Recuperar el evento original del escenario.
            original_event = db.session.get(
                Event,
                scenario["event_id"]
            )

            assert original_event is not None, (
                "No se encontro el evento original"
            )

            assert original_event.tenant_id == scenario["tenant_id"], (
                "El evento original pertenece a otro tenant"
            )

            # Reutilizar el cliente del evento original.
            event = Event(
                tenant_id=scenario["tenant_id"],
                client_id=original_event.client_id,
                name=f"Evento disponibilidad {uuid4().hex[:8]}",
                event_type="social",
                starts_at=starts_at,
                ends_at=ends_at,
                status="draft",
            )

            db.session.add(event)
            db.session.flush()

            event_id = event.id

            db.session.commit()

            return event_id

        except Exception:
            db.session.rollback()
            raise

        finally:
            db.session.remove()

def get_available_quantity(scenario, starts_at, ends_at):
    response = requests.get(
        f"{scenario['base_url']}/inventory/availability",
        headers=scenario["headers"],
        params={
            "item_id": scenario["item_id"],
            "starts_at": starts_at.isoformat() + "Z",
            "ends_at": ends_at.isoformat() + "Z",
        },
        timeout=45,
    )

    assert response.status_code == 200, response.text
    return response.json()["quantity_available"]


def test_overlapping_events_share_inventory(
    lifecycle_scenario,
    flask_app,
):
    scenario = lifecycle_scenario

    # Evento A reserva seis unidades.
    response = requests.post(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 6,
        },
        timeout=45,
    )

    assert response.status_code == 201, response.text

    # Evento B se traslapa parcialmente con A.
    starts_b = scenario["starts_at"] + timedelta(hours=2)
    ends_b = scenario["ends_at"] + timedelta(hours=2)

    event_b_id = create_second_event(
        scenario,
        flask_app,
        starts_b,
        ends_b,
    )

    available = get_available_quantity(
        scenario,
        starts_b,
        ends_b,
    )

    assert available == 4

    # No debe permitir reservar cinco unidades.
    response = requests.post(
        f"{scenario['base_url']}/events/"
        f"{event_b_id}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 5,
        },
        timeout=45,
    )

    assert response.status_code == 409, response.text

    # Sí debe permitir reservar las cuatro disponibles.
    response = requests.post(
        f"{scenario['base_url']}/events/"
        f"{event_b_id}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 4,
        },
        timeout=45,
    )

    assert response.status_code == 201, response.text


def test_non_overlapping_events_reuse_inventory(
    lifecycle_scenario,
    flask_app,
):
    scenario = lifecycle_scenario

    # Evento A reserva seis unidades.
    response = requests.post(
        f"{scenario['base_url']}/events/"
        f"{scenario['event_id']}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 6,
        },
        timeout=45,
    )

    assert response.status_code == 201, response.text

    # Evento B comienza un día después de A.
    starts_b = scenario["ends_at"] + timedelta(days=1)
    ends_b = starts_b + timedelta(hours=6)

    event_b_id = create_second_event(
        scenario,
        flask_app,
        starts_b,
        ends_b,
    )

    available = get_available_quantity(
        scenario,
        starts_b,
        ends_b,
    )

    assert available == 10

    response = requests.post(
        f"{scenario['base_url']}/events/"
        f"{event_b_id}/reservations",
        headers=scenario["headers"],
        json={
            "inventory_item_id": scenario["item_id"],
            "quantity": 10,
        },
        timeout=45,
    )

    assert response.status_code == 201, response.text
