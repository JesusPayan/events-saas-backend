"""Sprint 4.3: aislamiento de reservas y disponibilidad entre empresas."""
import pytest
from app.extensions import db
from app.models.inventory_reservation import InventoryReservation
from tests.test_identity import client  # noqa: F401
from tests.test_client_isolation import tenants, create_customer  # noqa: F401
from tests.test_inventory_isolation import create_category, create_item

START = '2027-03-10T16:00:00Z'
END = '2027-03-10T21:00:00Z'


def create_event_for(client, headers, customer_id, name):
    response = client.post('/api/v1/events', headers=headers, json={
        'client_id': customer_id, 'name': name, 'event_type': 'wedding',
        'starts_at': START, 'ends_at': END, 'estimated_guests': 100,
    })
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def reserve(client, headers, event_id, item_id, quantity):
    return client.post(f'/api/v1/events/{event_id}/reservations', headers=headers,
                       json={'inventory_item_id': item_id, 'quantity': quantity})


def availability(client, headers, item_id):
    return client.get('/api/v1/inventory/availability', headers=headers,
                      query_string={'item_id': item_id, 'starts_at': START, 'ends_at': END})


@pytest.fixture
def reservation_data(tenants):
    c = tenants['client']
    ha, hb = tenants['headers_a'], tenants['headers_b']
    ca = create_category(c, ha, 'Reservas A')
    cb = create_category(c, hb, 'Reservas B')
    ia = create_item(c, ha, 'RES-A-001', 'Silla reservable A', ca['id'])
    ib = create_item(c, hb, 'RES-B-001', 'Silla reservable B', cb['id'])
    customer_a = create_customer(c, ha, 'ReservaA')
    customer_b = create_customer(c, hb, 'ReservaB')
    ea = create_event_for(c, ha, customer_a['id'], 'Evento reservas A')
    eb = create_event_for(c, hb, customer_b['id'], 'Evento reservas B')
    return {**tenants, 'item_a': ia, 'item_b': ib, 'event_a': ea, 'event_b': eb}


def test_cannot_list_other_tenant_event_reservations(reservation_data):
    d = reservation_data
    r = d['client'].get(f"/api/v1/events/{d['event_b']['id']}/reservations", headers=d['headers_a'])
    assert r.status_code == 404, r.get_json()
    assert r.get_json()['error'] == 'event_not_found'


def test_cannot_reserve_other_tenant_item(reservation_data):
    d = reservation_data
    r = reserve(d['client'], d['headers_a'], d['event_a']['id'], d['item_b']['id'], 2)
    assert r.status_code == 404, r.get_json()
    assert r.get_json()['error'] == 'item_not_found'


def test_cannot_reserve_for_other_tenant_event(reservation_data):
    d = reservation_data
    r = reserve(d['client'], d['headers_a'], d['event_b']['id'], d['item_a']['id'], 2)
    assert r.status_code == 404, r.get_json()
    assert r.get_json()['error'] == 'event_not_found'


def test_cannot_cancel_other_tenant_reservation(reservation_data):
    d = reservation_data
    c = d['client']
    created = reserve(c, d['headers_b'], d['event_b']['id'], d['item_b']['id'], 2)
    assert created.status_code == 201, created.get_json()
    reservation_id = created.get_json()['id']
    r = c.patch(f"/api/v1/events/{d['event_b']['id']}/reservations/{reservation_id}/cancel",
                headers=d['headers_a'])
    assert r.status_code == 404, r.get_json()
    db.session.expire_all()
    assert db.session.get(InventoryReservation, reservation_id).status == 'reserved'


def test_availability_rejects_other_tenant_item(reservation_data):
    d = reservation_data
    r = availability(d['client'], d['headers_a'], d['item_b']['id'])
    assert r.status_code == 404, r.get_json()
    assert r.get_json()['error'] == 'item_not_found'


def test_reservation_stores_correct_tenant(reservation_data):
    d = reservation_data
    r = reserve(d['client'], d['headers_a'], d['event_a']['id'], d['item_a']['id'], 3)
    assert r.status_code == 201, r.get_json()
    reservation = db.session.get(InventoryReservation, r.get_json()['id'])
    assert reservation.tenant_id == d['tenant_a']
    assert reservation.event_id == d['event_a']['id']
    assert reservation.inventory_item_id == d['item_a']['id']


def test_invalid_reservation_quantities_rejected(reservation_data):
    d = reservation_data
    for quantity in (0, -1, 1.5, True, '2'):
        r = reserve(d['client'], d['headers_a'], d['event_a']['id'], d['item_a']['id'], quantity)
        assert r.status_code == 400, (quantity, r.get_json())
        assert r.get_json()['error'] == 'invalid_payload'


def test_reservation_cannot_exceed_availability(reservation_data):
    d = reservation_data
    r = reserve(d['client'], d['headers_a'], d['event_a']['id'], d['item_a']['id'], 11)
    assert r.status_code == 409, r.get_json()
    assert r.get_json()['error'] == 'insufficient_inventory'


def test_cancel_releases_availability(reservation_data):
    d = reservation_data
    c, h = d['client'], d['headers_a']
    created = reserve(c, h, d['event_a']['id'], d['item_a']['id'], 4)
    assert created.status_code == 201, created.get_json()
    before = availability(c, h, d['item_a']['id'])
    assert before.status_code == 200, before.get_json()
    assert before.get_json()['quantity_reserved'] == 4
    assert before.get_json()['quantity_available'] == 6
    reservation_id = created.get_json()['id']
    cancelled = c.patch(f"/api/v1/events/{d['event_a']['id']}/reservations/{reservation_id}/cancel", headers=h)
    assert cancelled.status_code == 200, cancelled.get_json()
    assert cancelled.get_json()['status'] == 'cancelled'
    after = availability(c, h, d['item_a']['id'])
    assert after.status_code == 200, after.get_json()
    assert after.get_json()['quantity_reserved'] == 0
    assert after.get_json()['quantity_available'] == 10
