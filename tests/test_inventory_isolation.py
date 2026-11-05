"""Sprint 4.3: aislamiento multiempresa de artículos y categorías."""
import pytest
from app.extensions import db
from app.models.inventory_item import InventoryItem
from app.models.inventory_category import InventoryCategory
from tests.test_identity import client  # noqa: F401 - fixture requerido por tenants
from tests.test_client_isolation import tenants  # noqa: F401


def create_category(client, headers, name):
    response = client.post('/api/v1/inventory/categories', headers=headers, json={'name': name})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def create_item(client, headers, sku, name, category_id=None):
    payload = {'sku': sku, 'name': name, 'item_type': 'product', 'quantity_total': 10, 'unit': 'piece'}
    if category_id is not None:
        payload['category_id'] = category_id
    response = client.post('/api/v1/inventory/items', headers=headers, json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


@pytest.fixture
def inventory_data(tenants):
    client = tenants['client']
    ha, hb = tenants['headers_a'], tenants['headers_b']
    ca = create_category(client, ha, 'Mobiliario A')
    cb = create_category(client, hb, 'Mobiliario B')
    ia = create_item(client, ha, 'SKU-A-001', 'Silla A', ca['id'])
    ib = create_item(client, hb, 'SKU-B-001', 'Silla B', cb['id'])
    return {**tenants, 'category_a': ca, 'category_b': cb, 'item_a': ia, 'item_b': ib}


def test_items_list_isolated(inventory_data):
    d = inventory_data
    response = d['client'].get('/api/v1/inventory/items', headers=d['headers_a'])
    assert response.status_code == 200, response.get_json()
    ids = {x['id'] for x in response.get_json()['items']}
    assert d['item_a']['id'] in ids
    assert d['item_b']['id'] not in ids


def test_categories_list_isolated(inventory_data):
    d = inventory_data
    response = d['client'].get('/api/v1/inventory/categories', headers=d['headers_a'])
    assert response.status_code == 200, response.get_json()
    ids = {x['id'] for x in response.get_json()}
    assert d['category_a']['id'] in ids
    assert d['category_b']['id'] not in ids


def test_cannot_read_other_tenant_item(inventory_data):
    d = inventory_data
    r = d['client'].get(f"/api/v1/inventory/items/{d['item_b']['id']}", headers=d['headers_a'])
    assert r.status_code == 404, r.get_json()


def test_cannot_update_other_tenant_item(inventory_data):
    d = inventory_data
    r = d['client'].patch(f"/api/v1/inventory/items/{d['item_b']['id']}", headers=d['headers_a'], json={'name': 'Intrusión'})
    assert r.status_code == 404, r.get_json()
    assert db.session.get(InventoryItem, d['item_b']['id']).name == 'Silla B'


def test_cannot_deactivate_other_tenant_item(inventory_data):
    d = inventory_data
    r = d['client'].patch(f"/api/v1/inventory/items/{d['item_b']['id']}/deactivate", headers=d['headers_a'])
    assert r.status_code == 404, r.get_json()
    assert db.session.get(InventoryItem, d['item_b']['id']).is_active is True


def test_cannot_read_other_tenant_category(inventory_data):
    d = inventory_data
    r = d['client'].get(f"/api/v1/inventory/categories/{d['category_b']['id']}", headers=d['headers_a'])
    assert r.status_code == 404, r.get_json()


def test_cannot_update_other_tenant_category(inventory_data):
    d = inventory_data
    r = d['client'].patch(f"/api/v1/inventory/categories/{d['category_b']['id']}", headers=d['headers_a'], json={'name': 'Intrusión'})
    assert r.status_code == 404, r.get_json()
    assert db.session.get(InventoryCategory, d['category_b']['id']).name == 'Mobiliario B'


def test_cannot_deactivate_other_tenant_category(inventory_data):
    d = inventory_data
    r = d['client'].patch(f"/api/v1/inventory/categories/{d['category_b']['id']}/deactivate", headers=d['headers_a'])
    assert r.status_code == 404, r.get_json()
    assert db.session.get(InventoryCategory, d['category_b']['id']).is_active is True


def test_cannot_create_item_with_other_tenant_category(inventory_data):
    d = inventory_data
    r = d['client'].post('/api/v1/inventory/items', headers=d['headers_a'], json={
        'sku': 'CROSS-CATEGORY', 'name': 'Artículo inválido', 'category_id': d['category_b']['id']
    })
    assert r.status_code == 404, r.get_json()
    assert r.get_json()['error'] == 'category_not_found'


def test_cannot_assign_other_tenant_category(inventory_data):
    d = inventory_data
    r = d['client'].patch(f"/api/v1/inventory/items/{d['item_a']['id']}", headers=d['headers_a'], json={
        'category_id': d['category_b']['id']
    })
    assert r.status_code == 404, r.get_json()
    assert db.session.get(InventoryItem, d['item_a']['id']).category_id == d['category_a']['id']


def test_items_and_categories_store_correct_tenant(inventory_data):
    d = inventory_data
    assert db.session.get(InventoryItem, d['item_a']['id']).tenant_id == d['tenant_a']
    assert db.session.get(InventoryItem, d['item_b']['id']).tenant_id == d['tenant_b']
    assert db.session.get(InventoryCategory, d['category_a']['id']).tenant_id == d['tenant_a']
    assert db.session.get(InventoryCategory, d['category_b']['id']).tenant_id == d['tenant_b']
