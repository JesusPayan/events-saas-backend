
"""Sprint 4.3.1: seguridad multiempresa y reglas de movimientos."""
import pytest
from app.extensions import db
from app.models.inventory_movement import InventoryMovement
from tests.test_identity import client  # noqa: F401
from tests.test_client_isolation import tenants  # noqa: F401
from tests.test_inventory_reservation_isolation import reservation_data, reserve  # noqa: F401

BASE = '/api/v1/inventory/movements'


def movement(client, headers, kind, reservation_id, quantity, **extra):
    return client.post(f'{BASE}/{kind}', headers=headers,
                       json={'reservation_id': reservation_id, 'quantity': quantity, **extra})


def create_reservation(d, side='a', quantity=5):
    response = reserve(d['client'], d[f'headers_{side}'],
                       d[f'event_{side}']['id'], d[f'item_{side}']['id'], quantity)
    assert response.status_code == 201, response.get_json()
    return response.get_json()['id']


def assert_error(response, status, code):
    assert response.status_code == status, response.get_json()
    assert response.get_json()['error'] == code


def test_cannot_dispatch_other_tenant_reservation(reservation_data):
    d = reservation_data
    rid = create_reservation(d, 'b')
    assert_error(movement(d['client'], d['headers_a'], 'dispatch', rid, 1),
                 404, 'reservation_not_found')
    assert db.session.query(InventoryMovement).count() == 0


def test_cannot_return_other_tenant_reservation(reservation_data):
    d = reservation_data
    rid = create_reservation(d, 'b')
    dispatched = movement(d['client'], d['headers_b'], 'dispatch', rid, 2)
    assert dispatched.status_code == 201, dispatched.get_json()
    assert_error(movement(d['client'], d['headers_a'], 'return', rid, 1),
                 404, 'reservation_not_found')
    assert db.session.query(InventoryMovement).count() == 1


def test_cannot_list_other_tenant_movements(reservation_data):
    d = reservation_data
    rid = create_reservation(d, 'b')
    assert_error(d['client'].get(BASE, headers=d['headers_a'],
                                 query_string={'reservation_id': rid}),
                 404, 'reservation_not_found')


def test_dispatch_stores_correct_tenant_and_actor(reservation_data):
    d = reservation_data
    rid = create_reservation(d)
    response = movement(d['client'], d['headers_a'], 'dispatch', rid, 3)
    assert response.status_code == 201, response.get_json()
    data = response.get_json()['movement']
    record = db.session.get(InventoryMovement, data['id'])
    assert record.tenant_id == d['tenant_a']
    assert record.reservation_id == rid
    assert record.inventory_item_id == d['item_a']['id']
    assert record.created_by is not None
    assert record.quantity == 3
    assert record.movement_type == 'dispatch'


def test_cannot_dispatch_more_than_reserved(reservation_data):
    d = reservation_data
    rid = create_reservation(d, quantity=3)
    assert_error(movement(d['client'], d['headers_a'], 'dispatch', rid, 4),
                 409, 'dispatch_exceeds_reservation')


def test_cannot_dispatch_more_than_remaining(reservation_data):
    d = reservation_data
    rid = create_reservation(d, quantity=5)
    assert movement(d['client'], d['headers_a'], 'dispatch', rid, 4).status_code == 201
    assert_error(movement(d['client'], d['headers_a'], 'dispatch', rid, 2),
                 409, 'dispatch_exceeds_reservation')


def test_cannot_return_without_dispatch(reservation_data):
    d = reservation_data
    rid = create_reservation(d)
    assert_error(movement(d['client'], d['headers_a'], 'return', rid, 1),
                 409, 'nothing_to_return')


def test_cannot_return_more_than_outstanding(reservation_data):
    d = reservation_data
    rid = create_reservation(d)
    assert movement(d['client'], d['headers_a'], 'dispatch', rid, 2).status_code == 201
    assert_error(movement(d['client'], d['headers_a'], 'return', rid, 3),
                 409, 'return_exceeds_outstanding')


def test_dispatch_return_and_summary(reservation_data):
    d = reservation_data
    rid = create_reservation(d)
    assert movement(d['client'], d['headers_a'], 'dispatch', rid, 4).status_code == 201
    returned = movement(d['client'], d['headers_a'], 'return', rid, 3)
    assert returned.status_code == 201, returned.get_json()
    summary = returned.get_json()['summary']
    assert summary['quantity_dispatched'] == 4
    assert summary['quantity_returned'] == 3
    assert summary['quantity_outstanding'] == 1
    listing = d['client'].get(BASE, headers=d['headers_a'],
                              query_string={'reservation_id': rid})
    assert listing.status_code == 200, listing.get_json()
    assert len(listing.get_json()['items']) == 2
    assert all(m['tenant_id'] == d['tenant_a'] for m in listing.get_json()['items'])


@pytest.mark.parametrize('quantity', [0, -1, 1.5, True, '2', None])
def test_invalid_movement_quantity_rejected(reservation_data, quantity):
    d = reservation_data
    rid = create_reservation(d)
    response = movement(d['client'], d['headers_a'], 'dispatch', rid, quantity)
    assert response.status_code == 400, response.get_json()


def test_client_supplied_tenant_is_ignored(reservation_data):
    d = reservation_data
    rid = create_reservation(d)
    response = movement(d['client'], d['headers_a'], 'dispatch', rid, 1,
                        tenant_id=d['tenant_b'])
    assert response.status_code == 201, response.get_json()
    assert response.get_json()['movement']['tenant_id'] == d['tenant_a']
