
from decimal import Decimal

import pytest
from app.extensions import db
from app.models.inventory_incident import InventoryIncident
from app.models.inventory_incident_charge import InventoryIncidentCharge
from app.models.inventory_charge_audit import InventoryChargeAudit
from tests.test_identity import client  # noqa: F401
from tests.test_client_isolation import tenants  # noqa: F401
from tests.test_inventory_reservation_isolation import reservation_data, reserve  # noqa: F401

BASE = '/api/v1/inventory/charges'


def actor_id(client, headers):
    response = client.get(
        "/api/v1/auth/me",
        headers=headers
    )

    assert response.status_code == 200, response.get_json()

    return int(response.get_json()["id"])


def create_charge(d, side='a', amount='250.00'):
    client = d['client']
    headers = d[f'headers_{side}']
    tenant_id = d[f'tenant_{side}']
    event_id = d[f'event_{side}']['id']
    item_id = d[f'item_{side}']['id']
    response = reserve(client, headers, event_id, item_id, 2)
    assert response.status_code == 201, response.get_json()
    reservation_id = response.get_json()['id']
    user_id = actor_id(d["client"], headers)
    incident = InventoryIncident(
        tenant_id=tenant_id,
        reservation_id=reservation_id,
        inventory_item_id=item_id,
        incident_type='damaged',
        quantity=1,
        description='Daño registrado en prueba',
        status='assessed',
        reported_by=user_id,
    )
    db.session.add(incident)
    db.session.flush()
    charge = InventoryIncidentCharge(
        tenant_id=tenant_id,
        incident_id=incident.id,
        event_id=event_id,
        amount=Decimal(amount),
        currency='MXN',
        status='pending',
        description='Cargo de prueba',
        created_by=user_id,
    )
    db.session.add(charge)
    db.session.commit()
    return charge.id


def action(d, side, charge_id, name, payload=None):
    return d['client'].post(
        f'{BASE}/{charge_id}/{name}',
        headers=d[f'headers_{side}'],
        json={} if payload is None else payload,
    )


def assert_error(response, status, code):
    assert response.status_code == status, response.get_json()
    assert response.get_json()['error'] == code


def test_charges_list_isolated(reservation_data):
    d = reservation_data
    own = create_charge(d, 'a')
    foreign = create_charge(d, 'b')
    response = d['client'].get(BASE, headers=d['headers_a'])
    assert response.status_code == 200, response.get_json()
    ids = {entry['id'] for entry in response.get_json()['items']}
    assert own in ids
    assert foreign not in ids


@pytest.mark.parametrize('operation,payload', [
    ('approve', {}),
    ('waive', {'notes': 'Condonación justificada'}),
    ('pay', {'payment_reference': 'TRX-1', 'payment_method': 'transfer'}),
])
def test_cannot_modify_other_tenant_charge(reservation_data, operation, payload):
    d = reservation_data
    foreign = create_charge(d, 'b')
    assert_error(action(d, 'a', foreign, operation, payload), 404, 'charge_not_found')
    db.session.expire_all()
    assert db.session.get(InventoryIncidentCharge, foreign).status == 'pending'
    assert db.session.query(InventoryChargeAudit).count() == 0

# ============================================================
# Sprint 4.3.2 - Transiciones, validaciones y auditoría
# ============================================================


def test_approve_own_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    response = action(d, 'a', charge_id, 'approve')

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data['id'] == charge_id
    assert data['status'] == 'approved'
    assert data['tenant_id'] == d['tenant_a']
    assert data['approved_at'] is not None

    db.session.expire_all()

    charge = db.session.get(InventoryIncidentCharge, charge_id)
    assert charge.status == 'approved'
    assert charge.approved_by == actor_id(
        d['client'], d['headers_a']
    )


def test_pay_approved_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    approved = action(d, 'a', charge_id, 'approve')
    assert approved.status_code == 200, approved.get_json()

    response = action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': 'TRX-2026-001',
            'payment_method': 'transfer'
        }
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data['status'] == 'paid'
    assert data['payment_reference'] == 'TRX-2026-001'
    assert data['payment_method'] == 'transfer'
    assert data['paid_at'] is not None


def test_waive_pending_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    response = action(
        d, 'a', charge_id, 'waive',
        {'notes': 'Condonación autorizada por administración'}
    )

    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data['status'] == 'waived'
    assert data['resolution_notes'] == (
        'Condonación autorizada por administración'
    )
    assert data['waived_at'] is not None


def test_waive_approved_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    approved = action(d, 'a', charge_id, 'approve')
    assert approved.status_code == 200, approved.get_json()

    response = action(
        d, 'a', charge_id, 'waive',
        {'notes': 'Condonación posterior a aprobación'}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['status'] == 'waived'


def test_cannot_pay_pending_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    response = action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': 'TRX-001',
            'payment_method': 'transfer'
        }
    )

    assert_error(
        response, 409, 'invalid_charge_transition'
    )


def test_cannot_approve_paid_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    assert action(
        d, 'a', charge_id, 'approve'
    ).status_code == 200

    assert action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': 'TRX-002',
            'payment_method': 'cash'
        }
    ).status_code == 200

    response = action(d, 'a', charge_id, 'approve')

    assert_error(
        response, 409, 'invalid_charge_transition'
    )


def test_cannot_pay_waived_charge(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    assert action(
        d, 'a', charge_id, 'waive',
        {'notes': 'Condonación definitiva'}
    ).status_code == 200

    response = action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': 'TRX-003',
            'payment_method': 'transfer'
        }
    )

    assert_error(
        response, 409, 'invalid_charge_transition'
    )


@pytest.mark.parametrize('notes', [
    None,
    '',
    '   '
])
def test_waive_requires_reason(reservation_data, notes):
    d = reservation_data
    charge_id = create_charge(d)

    response = action(
        d, 'a', charge_id, 'waive',
        {'notes': notes}
    )

    assert_error(
        response, 400, 'waiver_reason_required'
    )


@pytest.mark.parametrize('reference', [
    None,
    '',
    '   ',
    'X' * 121
])
def test_invalid_payment_reference(reservation_data, reference):
    d = reservation_data
    charge_id = create_charge(d)

    assert action(
        d, 'a', charge_id, 'approve'
    ).status_code == 200

    response = action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': reference,
            'payment_method': 'transfer'
        }
    )

    assert_error(
        response, 400, 'invalid_payment_reference'
    )


def test_invalid_payment_method(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    assert action(
        d, 'a', charge_id, 'approve'
    ).status_code == 200

    response = action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': 'TRX-004',
            'payment_method': 'bitcoin'
        }
    )

    assert_error(
        response, 400, 'invalid_payment_method'
    )


def test_approval_creates_audit(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    response = action(d, 'a', charge_id, 'approve')
    assert response.status_code == 200, response.get_json()

    audits = db.session.query(InventoryChargeAudit).filter_by(
        tenant_id=d['tenant_a'],
        charge_id=charge_id
    ).all()

    assert len(audits) == 1
    assert audits[0].previous_status == 'pending'
    assert audits[0].new_status == 'approved'
    assert audits[0].changed_by == actor_id(
        d['client'], d['headers_a']
    )


def test_payment_creates_audit_history(reservation_data):
    d = reservation_data
    charge_id = create_charge(d)

    assert action(
        d, 'a', charge_id, 'approve'
    ).status_code == 200

    assert action(
        d, 'a', charge_id, 'pay',
        {
            'payment_reference': 'TRX-005',
            'payment_method': 'card'
        }
    ).status_code == 200

    response = d['client'].get(
        f'{BASE}/{charge_id}/audit',
        headers=d['headers_a']
    )

    assert response.status_code == 200, response.get_json()

    audits = response.get_json()['items']

    assert len(audits) == 2
    assert audits[0]['previous_status'] == 'pending'
    assert audits[0]['new_status'] == 'approved'
    assert audits[1]['previous_status'] == 'approved'
    assert audits[1]['new_status'] == 'paid'

    assert all(
        audit['tenant_id'] == d['tenant_a']
        for audit in audits
    )


def test_cannot_read_other_tenant_audit(reservation_data):
    d = reservation_data
    foreign_charge_id = create_charge(d, 'b')

    response = d['client'].get(
        f'{BASE}/{foreign_charge_id}/audit',
        headers=d['headers_a']
    )

    assert_error(
        response, 404, 'charge_not_found'
    )
