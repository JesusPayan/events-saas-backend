
import os
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import text

from sqlalchemy import (
    create_engine,
    text,
)
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def engine():
    url = os.getenv("DB_URL_TEST")

    if not url:
        pytest.skip("DB_URL_TEST no configurada")

    if not url.rsplit("/", 1)[-1].split("?", 1)[0].endswith(
        ("_test", "_ci_validation")
    ):
        pytest.fail("La base configurada no es de pruebas")

    engine = create_engine(url, pool_pre_ping=True)

    yield engine

    engine.dispose()


def test_reservation_tenant_foreign_keys_exist(engine):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT CONSTRAINT_NAME
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'inventory_reservations'
              AND CONSTRAINT_TYPE = 'FOREIGN KEY'
              AND CONSTRAINT_NAME IN (
                  'fk_reservation_event_tenant',
                  'fk_reservation_item_tenant'
              )
        """)).scalars().all()

    assert set(rows) == {
        "fk_reservation_event_tenant",
        "fk_reservation_item_tenant",
    }


def test_reservation_quantity_check_exists(engine):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT CONSTRAINT_NAME
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'inventory_reservations'
              AND CONSTRAINT_TYPE = 'CHECK'
              AND CONSTRAINT_NAME =
                  'ck_reservation_quantity_positive'
        """)).scalars().all()

    assert rows == ["ck_reservation_quantity_positive"]


def test_reservation_tenant_indexes_exist(engine):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'inventory_reservations'
              AND INDEX_NAME IN (
                  'uq_reservation_event_item',
                  'uq_inventory_reservation_tenant_id'
              )
        """)).scalars().all()

    assert set(rows) == {
        "uq_reservation_event_item",
        "uq_inventory_reservation_tenant_id",
    }

@pytest.fixture
def tenant_inventory_data(engine):
    """Obtiene dos tenants con evento y artículo válidos."""
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT
                t.id AS tenant_id,
                (
                    SELECT e.id
                    FROM events e
                    WHERE e.tenant_id = t.id
                    ORDER BY e.id
                    LIMIT 1
                ) AS event_id,
                (
                    SELECT i.id
                    FROM inventory_items i
                    WHERE i.tenant_id = t.id
                    ORDER BY i.id
                    LIMIT 1
                ) AS item_id
            FROM tenants t
            WHERE EXISTS (
                SELECT 1 FROM events e
                WHERE e.tenant_id = t.id
            )
            AND EXISTS (
                SELECT 1 FROM inventory_items i
                WHERE i.tenant_id = t.id
            )
            ORDER BY t.id
            LIMIT 2
        """)).mappings().all()

    if len(rows) < 2:
        pytest.skip(
            "Se necesitan dos tenants con eventos "
            "y artículos para esta prueba"
        )

    return rows[0], rows[1]


def insert_reservation(
    connection,
    tenant_id,
    event_id,
    item_id,
):
    return connection.execute(text("""
        INSERT INTO inventory_reservations (
            tenant_id,
            event_id,
            inventory_item_id,
            quantity,
            status,
            created_at,
            updated_at
        )
        VALUES (
            :tenant_id,
            :event_id,
            :item_id,
            1,
            'reserved',
            :now,
            :now
        )
    """), {
        "tenant_id": tenant_id,
        "event_id": event_id,
        "item_id": item_id,
        "now": datetime.now(timezone.utc).replace(
            tzinfo=None
        ),
    })


def test_rejects_event_from_another_tenant(
    engine,
    tenant_inventory_data,
):
    tenant_a, tenant_b = tenant_inventory_data

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(IntegrityError):
                insert_reservation(
                    connection,
                    tenant_a["tenant_id"],
                    tenant_b["event_id"],
                    tenant_a["item_id"],
                )
        finally:
            transaction.rollback()


def test_rejects_item_from_another_tenant(
    engine,
    tenant_inventory_data,
):
    tenant_a, tenant_b = tenant_inventory_data

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(IntegrityError):
                insert_reservation(
                    connection,
                    tenant_a["tenant_id"],
                    tenant_a["event_id"],
                    tenant_b["item_id"],
                )
        finally:
            transaction.rollback()

def _create_tenant_data(connection, suffix, label):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    tenant = connection.execute(text("""
        INSERT INTO tenants (
            name, slug, status, timezone, created_at
        )
        VALUES (
            :name, :slug, 'active',
            'America/Mexico_City', :now
        )
    """), {
        "name": f"Test Tenant {label}",
        "slug": f"test-tenant-{suffix}-{label.lower()}",
        "now": now,
    })
    tenant_id = tenant.lastrowid

    client = connection.execute(text("""
        INSERT INTO clients (
            tenant_id, client_type, first_name,
            last_name, status, created_at, updated_at
        )
        VALUES (
            :tenant_id, 'person', :first_name,
            'Test', 'active', :now, :now
        )
    """), {
        "tenant_id": tenant_id,
        "first_name": f"Client {label}",
        "now": now,
    })
    client_id = client.lastrowid

    event = connection.execute(text("""
        INSERT INTO events (
            tenant_id, client_id, name, event_type,
            starts_at, ends_at, status,
            created_at, updated_at
        )
        VALUES (
            :tenant_id, :client_id, :name, 'social',
            :starts_at, :ends_at, 'draft',
            :now, :now
        )
    """), {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "name": f"Test Event {label}",
        "starts_at": now + timedelta(days=7),
        "ends_at": now + timedelta(days=7, hours=5),
        "now": now,
    })
    event_id = event.lastrowid

    item = connection.execute(text("""
        INSERT INTO inventory_items (
            tenant_id, category_id, sku, name,
            item_type, quantity_total, unit,
            is_active, created_at, updated_at
        )
        VALUES (
            :tenant_id, NULL, :sku, :name,
            'physical', 10, 'piece',
            1, :now, :now
        )
    """), {
        "tenant_id": tenant_id,
        "sku": f"SKU-{suffix}-{label}",
        "name": f"Test Item {label}",
        "now": now,
    })
    item_id = item.lastrowid

    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "event_id": event_id,
        "item_id": item_id,
    }


@pytest.fixture
def tenant_inventory_data(engine):
    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            suffix = uuid4().hex[:12]

            tenant_a = _create_tenant_data(
                connection, suffix, "A"
            )
            tenant_b = _create_tenant_data(
                connection, suffix, "B"
            )

            yield connection, tenant_a, tenant_b

        finally:
            transaction.rollback()
def test_valid_reservation_same_tenant(
    tenant_inventory_data,
):
    connection, tenant_a, _ = tenant_inventory_data

    result = insert_reservation(
        connection,
        tenant_a["tenant_id"],
        tenant_a["event_id"],
        tenant_a["item_id"],
    )

    assert result.rowcount == 1


def test_rejects_event_from_another_tenant(
    tenant_inventory_data,
):
    connection, tenant_a, tenant_b = tenant_inventory_data

    with pytest.raises(IntegrityError):
        insert_reservation(
            connection,
            tenant_a["tenant_id"],
            tenant_b["event_id"],
            tenant_a["item_id"],
        )


def test_rejects_item_from_another_tenant(
    tenant_inventory_data,
):
    connection, tenant_a, tenant_b = tenant_inventory_data

    with pytest.raises(IntegrityError):
        insert_reservation(
            connection,
            tenant_a["tenant_id"],
            tenant_a["event_id"],
            tenant_b["item_id"],
        )


def test_rejects_cross_tenant_reservation_update(
    tenant_inventory_data,
):
    connection, tenant_a, tenant_b = tenant_inventory_data

    result = insert_reservation(
        connection,
        tenant_a["tenant_id"],
        tenant_a["event_id"],
        tenant_a["item_id"],
    )

    reservation_id = result.lastrowid

    with pytest.raises(IntegrityError):
        connection.execute(text("""
            UPDATE inventory_reservations
            SET inventory_item_id = :item_id
            WHERE id = :reservation_id
        """), {
            "item_id": tenant_b["item_id"],
            "reservation_id": reservation_id,
        })
