
import os
from uuid import uuid4
import pytest
import requests
from app.extensions import db
from app.models import Tenant
from tests.conftest import test_context
from test_inventory_full_lifecycle import lifecycle_scenario
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.models.crm import Client
from app.models.event import Event
from app.models.inventory_item import InventoryItem
from app.models.inventory_reservation import InventoryReservation

from app.models.identity import User, Role, Membership
from app.security import issue_token
from app.models.inventory_movement import InventoryMovement

@pytest.fixture
def restricted_inventory_user(flask_app, test_context):
    """
    Usuario con membresía activa, pero con un rol
    independiente sin permisos de inventario.
    """
    suffix = uuid4().hex[:12]

    with flask_app.app_context():
        try:
            role = Role(
                tenant_id=test_context["tenant_id"],
                name=f"Restricted Inventory {suffix}",
            )

            db.session.add(role)
            db.session.flush()

            user = User(
                email=f"restricted-{suffix}@example.test",
                password_hash="test-not-for-login",
                is_active=True,
            )

            db.session.add(user)
            db.session.flush()

            membership = Membership(
                tenant_id=test_context["tenant_id"],
                user_id=user.id,
                role_id=role.id,
                status="active",
            )

            db.session.add(membership)
            db.session.flush()

            token = issue_token(user.id)
            db.session.commit()

            return {
                "tenant_id": test_context["tenant_id"],
                "token": token,
            }

        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()

def test_user_without_inventory_read_permission(
    restricted_inventory_user,
    lifecycle_scenario,
):
    s = lifecycle_scenario
    user = restricted_inventory_user

    response = requests.get(
        f"{s['base_url']}/inventory/movements",
        headers={
            "Authorization": f"Bearer {user['token']}",
            "X-Tenant-ID": str(user["tenant_id"]),
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"


@pytest.mark.parametrize(
    "operation",
    ["dispatch", "return"],
)
def test_user_without_inventory_update_permission(
    restricted_inventory_user,
    lifecycle_scenario,
    operation,
):
    s = lifecycle_scenario
    user = restricted_inventory_user

    response = requests.post(
        f"{s['base_url']}/inventory/movements/{operation}",
        headers={
            "Authorization": f"Bearer {user['token']}",
            "X-Tenant-ID": str(user["tenant_id"]),
        },
        json={
            "reservation_id": 1,
            "quantity": 1,
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"


@pytest.fixture
def two_tenant_inventory_scenario(
    flask_app,
    test_context,
    lifecycle_scenario,
):
    """
    Crea recursos propios de un segundo tenant.
    El usuario de A NO tiene membresía en B.
    """
    base_url = lifecycle_scenario["base_url"]
    suffix = uuid4().hex[:12]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    starts_at = now + timedelta(days=8)
    ends_at = starts_at + timedelta(hours=6)

    with flask_app.app_context():
        try:
            tenant_b = Tenant(
                name=f"Tenant B Isolation {suffix}",
                slug=f"tenant-b-isolation-{suffix}",
                status="active",
                timezone="America/Mexico_City",
            )

            db.session.add(tenant_b)
            db.session.flush()

            client_b = Client(
                tenant_id=tenant_b.id,
                client_type="individual",
                first_name="Cliente",
                last_name="Tenant B",
                status="active",
            )

            db.session.add(client_b)
            db.session.flush()

            event_b = Event(
                tenant_id=tenant_b.id,
                client_id=client_b.id,
                name=f"Evento B {suffix}",
                event_type="social",
                starts_at=starts_at,
                ends_at=ends_at,
                status="draft",
            )

            item_b = InventoryItem(
                tenant_id=tenant_b.id,
                sku=f"SEC-B-{suffix}",
                name="Articulo exclusivo B",
                item_type="product",
                quantity_total=10,
                quantity_unavailable=0,
                unit="piece",
                is_active=True,
            )

            db.session.add_all([event_b, item_b])
            db.session.flush()

            reservation_b = InventoryReservation(
                tenant_id=tenant_b.id,
                event_id=event_b.id,
                inventory_item_id=item_b.id,
                quantity=3,
                status="reserved",
            )

            db.session.add(reservation_b)
            db.session.flush()

            result = {
                "base_url": base_url,
                "tenant_a_id": test_context["tenant_id"],
                "tenant_b_id": tenant_b.id,
                "event_b_id": event_b.id,
                "item_b_id": item_b.id,
                "reservation_b_id": reservation_b.id,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "headers_a": lifecycle_scenario["headers"],
            }

            db.session.commit()
            return result

        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()


@pytest.mark.parametrize(
    "operation",
    ["list", "dispatch", "return"],
)
def test_cannot_access_foreign_tenant_movements(
    two_tenant_inventory_scenario,
    flask_app,
    operation,
):
    s = two_tenant_inventory_scenario

    url = f"{s['base_url']}/inventory/movements"

    def get_movement_count():
        with flask_app.app_context():
            try:
                return db.session.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.tenant_id
                        == s["tenant_b_id"],
                        InventoryMovement.reservation_id
                        == s["reservation_b_id"],
                    )
                )
            finally:
                db.session.remove()

    # Estado antes del intento no autorizado.
    movements_before = get_movement_count()

    if operation == "list":
        response = requests.get(
            url,
            headers=s["headers_a"],
            params={
                "reservation_id": s["reservation_b_id"]
            },
            timeout=45,
        )
    else:
        response = requests.post(
            f"{url}/{operation}",
            headers=s["headers_a"],
            json={
                "reservation_id": s["reservation_b_id"],
                "quantity": 1,
            },
            timeout=45,
        )

    # No debe permitir acceder a recursos de otro tenant.
    assert response.status_code == 404, response.text

    # No deben generarse movimientos nuevos.
    movements_after = get_movement_count()

    assert movements_after == movements_before, (
        f"Se detectaron movimientos inesperados "
        f"después de {operation}: "
        f"antes={movements_before}, "
        f"después={movements_after}"
    )

    # La reservación tampoco debe cambiar.
    with flask_app.app_context():
        try:
            reservation = db.session.scalar(
                select(InventoryReservation).where(
                    InventoryReservation.id
                    == s["reservation_b_id"],
                    InventoryReservation.tenant_id
                    == s["tenant_b_id"],
                )
            )

            assert reservation is not None
            assert reservation.quantity == 3
            assert reservation.status == "reserved"

        finally:
            db.session.remove()

def test_cannot_query_foreign_inventory_availability(
    two_tenant_inventory_scenario,
):
    s = two_tenant_inventory_scenario

    response = requests.get(
        f"{s['base_url']}/inventory/availability",
        headers=s["headers_a"],
        params={
            "item_id": s["item_b_id"],
            "starts_at": s["starts_at"].isoformat() + "Z",
            "ends_at": s["ends_at"].isoformat() + "Z",
        },
        timeout=45,
    )

    assert response.status_code in (403, 404), response.text

def test_cannot_cancel_foreign_tenant_reservation(
    two_tenant_inventory_scenario,
    flask_app,
):
    s = two_tenant_inventory_scenario

    response = requests.patch(
        f"{s['base_url']}/events/"
        f"{s['event_b_id']}/reservations/"
        f"{s['reservation_b_id']}/cancel",
        headers=s["headers_a"],
        timeout=45,
    )

    assert response.status_code == 404, response.text

    with flask_app.app_context():
        try:
            reservation = db.session.get(
                InventoryReservation,
                s["reservation_b_id"],
            )

            assert reservation is not None
            assert reservation.status == "reserved"

        finally:
            db.session.remove()

@pytest.mark.parametrize(
    "method,path,payload",
    [
        (
            "GET",
            "/inventory/movements",
            None,
        ),
        (
            "POST",
            "/inventory/movements/dispatch",
            {"quantity": 1},
        ),
        (
            "POST",
            "/inventory/movements/return",
            {"quantity": 1},
        ),
    ],
)
def test_cross_tenant_reservation_access(
    lifecycle_scenario,
    unauthorized_tenant,
    test_context,
    method,
    path,
    payload,
):
    scenario = lifecycle_scenario
    base_url = scenario["base_url"]

    reservation_response = requests.post(
    f"{base_url}/events/{scenario['event_id']}/reservations",
    headers=scenario["headers"],
    json={
        "inventory_item_id": scenario["item_id"],
        "quantity": 1,
    },
    timeout=45,
)

    assert reservation_response.status_code == 201, reservation_response.text

    reservation_id = reservation_response.json()["id"]

    # Token válido de A, pero tenant seleccionado B,
    # donde el usuario no tiene membresía.
    headers = {
    "Authorization": f"Bearer {test_context['token']}",
    "X-Tenant-ID": str(unauthorized_tenant),
    "Content-Type": "application/json",
}

    if method == "GET":
        response = requests.get(
            f"{base_url}{path}",
            headers=headers,
            params={"reservation_id": reservation_id},
            timeout=45,
        )
    else:
        response = requests.post(
            f"{base_url}{path}",
            headers=headers,
            json={
                "reservation_id": reservation_id,
                **payload,
            },
            timeout=45,
        )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"
@pytest.fixture
def unauthorized_tenant(flask_app, test_context):
    """
    Crea un tenant sin membresía para el usuario
    autenticado del fixture test_context.
    """
    with flask_app.app_context():
        tenant = Tenant(
            name="Tenant Isolation Test",
            slug=f"isolation-{uuid4().hex[:16]}",
            status="active",
            timezone="America/Mexico_City",
        )

        try:
            db.session.add(tenant)
            db.session.commit()
            tenant_id = tenant.id
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()

    return tenant_id


def test_user_cannot_access_tenant_without_membership(
    test_context,
    unauthorized_tenant,
):
    base_url = os.environ.get(
        "API_BASE_URL",
        "http://127.0.0.1:5001/api/v1",
    ).rstrip("/")

    response = requests.get(
        f"{base_url}/inventory/movements",
        headers={
            "Authorization": (
                f"Bearer {test_context['token']}"
            ),
            "X-Tenant-ID": str(unauthorized_tenant),
        },
        timeout=45,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "forbidden"