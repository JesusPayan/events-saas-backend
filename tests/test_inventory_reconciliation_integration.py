"""Sprint 4.5.2: conciliaciones exitosas y consistencia transaccional.

Ejecutar: python -m pytest tests/test_inventory_reconciliation_integration.py -v
"""
from decimal import Decimal

import pytest
from app.extensions import db
from app.models.inventory_item import InventoryItem
from app.models.inventory_incident import InventoryIncident
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_reconciliation_audit import InventoryReconciliationAudit
from app.models.inventory_capacity_alert import InventoryCapacityAlert
from app.services.inventory_movements import get_movement_summary
from tests.test_identity import client  # noqa: F401
from tests.test_client_isolation import tenants  # noqa: F401
from tests.test_inventory_reservation_isolation import reservation_data, reserve  # noqa: F401
from tests.test_inventory_charges_security import actor_id
from tests.test_inventory_movements_security import movement


def setup_case(d, kind='lost', quantity=1, dispatched=2, returned=0):
    http, headers = d['client'], d['headers_a']
    item_id = d['item_a']['id']
    response = reserve(http, headers, d['event_a']['id'], item_id, 2)
    assert response.status_code == 201, response.get_json()
    reservation_id = response.get_json()['id']
    if dispatched:
        response = movement(http, headers, 'dispatch', reservation_id, dispatched)
        assert response.status_code == 201, response.get_json()
    if returned:
        response = movement(http, headers, 'return', reservation_id, returned)
        assert response.status_code == 201, response.get_json()
    incident = InventoryIncident(
        tenant_id=d['tenant_a'], reservation_id=reservation_id,
        inventory_item_id=item_id, incident_type=kind,
        quantity=quantity, description='Conciliación de integración',
        status='assessed', reported_by=actor_id(http, headers),
    )
    db.session.add(incident)
    db.session.commit()
    return incident.id, reservation_id, item_id


def reconcile(d, incident_id, **payload):
    return d['client'].post(
        f'/api/v1/inventory/incidents/{incident_id}/reconcile',
        headers=d['headers_a'], json={'unit_cost': '100.00', **payload},
    )


def assert_records(incident_id, adjustment=1, charge=1, audit=1):
    assert db.session.query(InventoryAdjustment).filter_by(incident_id=incident_id).count() == adjustment
    assert db.session.query(InventoryIncidentCharge).filter_by(incident_id=incident_id).count() == charge
    assert db.session.query(InventoryReconciliationAudit).filter_by(incident_id=incident_id).count() == audit


def test_successful_loss_updates_inventory_and_creates_records(reservation_data):
    d = reservation_data
    incident_id, _, item_id = setup_case(d, 'lost')
    before = db.session.get(InventoryItem, item_id).quantity_total
    response = reconcile(d, incident_id)
    assert response.status_code == 200, response.get_json()
    db.session.expire_all()
    assert db.session.get(InventoryItem, item_id).quantity_total == before - 1
    assert db.session.get(InventoryIncident, incident_id).status == 'resolved'
    assert_records(incident_id)
    assert response.get_json()['adjustment']['adjustment_type'] == 'loss'


def test_loss_updates_administrative_outstanding(reservation_data):
    d = reservation_data
    incident_id, rid, _ = setup_case(d, 'lost')
    response = reconcile(d, incident_id)
    assert response.status_code == 200, response.get_json()
    summary = get_movement_summary(d['tenant_a'], rid)
    assert summary['quantity_dispatched'] == 2
    assert summary['quantity_lost'] == 1
    assert summary['quantity_physical_outstanding'] == 2
    assert summary['quantity_administrative_outstanding'] == 1


def test_successful_damage_quarantines_returned_stock(reservation_data):
    d = reservation_data
    incident_id, _, item_id = setup_case(d, 'damaged', dispatched=2, returned=1)
    item = db.session.get(InventoryItem, item_id)
    total, unavailable = item.quantity_total, item.quantity_unavailable
    response = reconcile(d, incident_id)
    assert response.status_code == 200, response.get_json()
    db.session.expire_all()
    item = db.session.get(InventoryItem, item_id)
    assert item.quantity_total == total
    assert item.quantity_unavailable == unavailable + 1
    assert response.get_json()['adjustment']['adjustment_type'] == 'quarantine'
    assert_records(incident_id)


def test_charge_amount_matches_quantity_times_unit_cost(reservation_data):
    d = reservation_data
    incident_id, _, _ = setup_case(d, 'lost', quantity=2)
    response = reconcile(d, incident_id, unit_cost='125.50')
    assert response.status_code == 200, response.get_json()
    db.session.expire_all()
    charge = db.session.query(InventoryIncidentCharge).filter_by(incident_id=incident_id).one()
    assert charge.amount == Decimal('251.00')
    assert charge.status == 'pending'
    assert db.session.get(InventoryIncident, incident_id).total_cost == Decimal('251.00')


def test_reconciliation_audit_records_before_and_after(reservation_data):
    d = reservation_data
    incident_id, _, item_id = setup_case(d, 'lost')
    before = db.session.get(InventoryItem, item_id).quantity_total
    response = reconcile(d, incident_id)
    assert response.status_code == 200, response.get_json()
    audit = db.session.query(InventoryReconciliationAudit).filter_by(incident_id=incident_id).one()
    assert audit.quantity_total_before == before
    assert audit.quantity_total_after == before - 1
    assert audit.quantity == 1
    assert audit.tenant_id == d['tenant_a']


def test_repeated_reconciliation_does_not_duplicate_records(reservation_data):
    d = reservation_data
    incident_id, _, _ = setup_case(d, 'lost')
    assert reconcile(d, incident_id).status_code == 200
    response = reconcile(d, incident_id)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()['error'] == 'incident_not_reconcilable'
    assert_records(incident_id)


def test_capacity_deficit_requires_explicit_acceptance(reservation_data):
    d = reservation_data
    incident_id, _, item_id = setup_case(d, 'lost')
    item = db.session.get(InventoryItem, item_id)
    item.quantity_total = 2
    item.quantity_unavailable = 0
    db.session.commit()
    response = reconcile(d, incident_id)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()['error'] == 'inventory_capacity_conflict'
    db.session.expire_all()
    assert db.session.get(InventoryItem, item_id).quantity_total == 2
    assert db.session.get(InventoryIncident, incident_id).status == 'assessed'
    assert_records(incident_id, 0, 0, 0)


def test_accepted_deficit_generates_capacity_alert(reservation_data):
    d = reservation_data
    incident_id, rid, item_id = setup_case(d, 'lost')
    item = db.session.get(InventoryItem, item_id)
    item.quantity_total = 2
    item.quantity_unavailable = 0
    db.session.commit()
    response = reconcile(d, incident_id, accept_deficit=True)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['capacity']['shortage_quantity'] == 1
    assert_records(incident_id)
    alerts = db.session.query(InventoryCapacityAlert).filter_by(
        tenant_id=d['tenant_a'], inventory_item_id=item_id,
        reservation_id=rid, status='open',
    ).all()
    assert len(alerts) == 1
    assert alerts[0].shortage_quantity == 1


@pytest.mark.parametrize('bad_cost', ['-1.00'])
def test_invalid_cost_does_not_change_inventory(reservation_data, bad_cost):
    d = reservation_data
    incident_id, _, item_id = setup_case(d, 'lost')
    before = db.session.get(InventoryItem, item_id).quantity_total
    response = reconcile(d, incident_id, unit_cost=bad_cost)
    assert response.status_code == 400, response.get_json()
    assert response.get_json()['error'] == 'invalid_unit_cost'
    db.session.expire_all()
    assert db.session.get(InventoryItem, item_id).quantity_total == before
    assert db.session.get(InventoryIncident, incident_id).status == 'assessed'
    assert_records(incident_id, 0, 0, 0)


def test_reconciliation_rolls_back_when_alert_sync_fails(reservation_data, monkeypatch):
    """Una falla después del flush no debe persistir inventario ni registros."""
    d = reservation_data
    incident_id, _, item_id = setup_case(d, 'lost')
    item = db.session.get(InventoryItem, item_id)
    before_total = item.quantity_total
    before_unavailable = item.quantity_unavailable

    def fail_alert_sync(*args, **kwargs):
        # El servicio ya actualizó el artículo y creó registros en la sesión.
        # Forzamos el fallo antes del commit para verificar atomicidad.
        raise RuntimeError('simulated_alert_sync_failure')

    monkeypatch.setattr(
        'app.services.inventory_reconciliation.synchronize_capacity_alerts',
        fail_alert_sync,
    )

    # En modo TESTING Flask propaga la excepción. Si el fixture captura
    # excepciones HTTP, también aceptamos una respuesta 500.
    try:
        response = reconcile(d, incident_id)
    except RuntimeError as exc:
        assert str(exc) == 'simulated_alert_sync_failure'
    else:
        assert response.status_code == 500, response.get_json()

    db.session.expire_all()
    item = db.session.get(InventoryItem, item_id)
    assert item.quantity_total == before_total
    assert item.quantity_unavailable == before_unavailable
    assert db.session.get(InventoryIncident, incident_id).status == 'assessed'
    assert_records(incident_id, 0, 0, 0)
