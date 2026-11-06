"""Sprint 4.5.2: seguridad y validaciones de conciliación de inventario.

Reutiliza los fixtures de integración existentes y no modifica los tests previos.
"""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.inventory_incident import InventoryIncident
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident_charge import InventoryIncidentCharge
from tests.test_identity import client  # noqa: F401
from tests.test_client_isolation import tenants  # noqa: F401
from tests.test_inventory_reservation_isolation import reservation_data, reserve  # noqa: F401

from tests.test_inventory_charges_security import actor_id


def make_incident(d, side='a', incident_type='damaged', quantity=1):
    http = d['client']
    headers = d[f'headers_{side}']
    tenant_id = d[f'tenant_{side}']
    event_id = d[f'event_{side}']['id']
    item_id = d[f'item_{side}']['id']
    response = reserve(http, headers, event_id, item_id, 2)
    assert response.status_code == 201, response.get_json()
    incident = InventoryIncident(
        tenant_id=tenant_id,
        reservation_id=response.get_json()['id'],
        inventory_item_id=item_id,
        incident_type=incident_type,
        quantity=quantity,
        description='Incidencia de prueba',
        status='assessed',
        reported_by=actor_id(http, headers),
    )
    db.session.add(incident)
    db.session.commit()
    return incident.id


def reconcile(d, side, incident_id, payload):
    return d['client'].post(
        f'/api/v1/inventory/incidents/{incident_id}/reconcile',
        headers=d[f'headers_{side}'],
        json=payload,
    )


def assert_error(response, status, code):
    assert response.status_code == status, response.get_json()
    assert response.get_json()['error'] == code


def assert_no_effects(incident_id):
    db.session.expire_all()
    incident = db.session.get(InventoryIncident, incident_id)
    assert incident.status == 'assessed'
    assert db.session.query(InventoryAdjustment).filter_by(incident_id=incident_id).count() == 0
    assert db.session.query(InventoryIncidentCharge).filter_by(incident_id=incident_id).count() == 0


def test_cannot_reconcile_other_tenant_incident(reservation_data):
    d = reservation_data
    foreign_id = make_incident(d, 'b')
    response = reconcile(d, 'a', foreign_id, {'unit_cost': '100.00'})
    assert_error(response, 404, 'incident_not_found')
    assert_no_effects(foreign_id)


@pytest.mark.parametrize('payload', [None, [], 'texto', 123])
def test_reconcile_rejects_non_object_json(reservation_data, payload):
    d = reservation_data
    incident_id = make_incident(d)
    response = reconcile(d, 'a', incident_id, payload)
    assert_error(response, 400, 'invalid_json')
    assert_no_effects(incident_id)


@pytest.mark.parametrize('value', ['yes', 1, None, []])
def test_reconcile_rejects_invalid_accept_deficit(reservation_data, value):
    d = reservation_data
    incident_id = make_incident(d)
    response = reconcile(d, 'a', incident_id, {
        'accept_deficit': value,
        'unit_cost': '100.00',
    })
    assert_error(response, 400, 'invalid_accept_deficit')
    assert_no_effects(incident_id)


def test_damage_without_return_is_rejected(reservation_data):
    d = reservation_data
    incident_id = make_incident(d, incident_type='damaged')
    response = reconcile(d, 'a', incident_id, {'unit_cost': '100.00'})
    assert_error(response, 409, 'damage_exceeds_returned')
    assert_no_effects(incident_id)


def test_loss_without_outstanding_is_rejected(reservation_data):
    d = reservation_data
    incident_id = make_incident(d, incident_type='lost')
    response = reconcile(d, 'a', incident_id, {'unit_cost': '100.00'})
    assert_error(response, 409, 'loss_exceeds_outstanding')
    assert_no_effects(incident_id)


def test_reconciliation_does_not_trust_payload_item_id(reservation_data):
    d = reservation_data
    incident_id = make_incident(d, incident_type='damaged')
    response = reconcile(d, 'a', incident_id, {
        'inventory_item_id': d['item_b']['id'],
        'unit_cost': '100.00',
    })
    assert_error(response, 409, 'damage_exceeds_returned')
    assert_no_effects(incident_id)
