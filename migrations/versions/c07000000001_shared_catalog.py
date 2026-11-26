"""NET-01: catálogo compartido entre organizaciones.

Aditiva: ``catalog_offers.shared`` (por defecto falso: nada se comparte sin
marcarlo) y columnas de partida de red en ``quote_items`` (organización
proveedora, oferta de la red, costo y estado del costo).

Revision ID: c07000000001
Revises: c06000000001
"""
from alembic import op
import sqlalchemy as sa

revision = 'c07000000001'
down_revision = 'c06000000001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('catalog_offers') as batch:
        batch.add_column(sa.Column('shared', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_index('ix_catalog_offers_shared_status', ['shared', 'status'])
    with op.batch_alter_table('quote_items') as batch:
        batch.add_column(sa.Column('supplier_tenant_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('network_offer_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('cost_unit_price', sa.Numeric(14, 2), nullable=True))
        batch.add_column(sa.Column('cost_status', sa.String(20), nullable=True))
        batch.create_foreign_key('fk_quote_items_supplier_tenant', 'tenants', ['supplier_tenant_id'], ['id'])
        batch.create_foreign_key('fk_quote_items_network_offer', 'catalog_offers', ['network_offer_id'], ['id'])
        batch.create_check_constraint('ck_quote_items_cost_status',
                                      "cost_status IS NULL OR cost_status IN ('confirmed', 'pending')")
        batch.create_check_constraint('ck_quote_items_cost_nonnegative',
                                      "cost_unit_price IS NULL OR cost_unit_price >= 0")
        batch.create_check_constraint(
            'ck_quote_items_network',
            "(supplier_tenant_id IS NULL AND network_offer_id IS NULL) "
            "OR (supplier_tenant_id IS NOT NULL AND network_offer_id IS NOT NULL "
            "AND supplier_tenant_id <> tenant_id AND item_type <> 'inventory')")
        batch.create_index('ix_quote_items_supplier', ['supplier_tenant_id'])


def downgrade():
    with op.batch_alter_table('quote_items') as batch:
        batch.drop_constraint('fk_quote_items_supplier_tenant', type_='foreignkey')
        batch.drop_constraint('fk_quote_items_network_offer', type_='foreignkey')
        batch.drop_constraint('ck_quote_items_cost_status', type_='check')
        batch.drop_constraint('ck_quote_items_cost_nonnegative', type_='check')
        batch.drop_constraint('ck_quote_items_network', type_='check')
        batch.drop_index('ix_quote_items_supplier')
        for column in ('cost_status', 'cost_unit_price', 'network_offer_id', 'supplier_tenant_id'):
            batch.drop_column(column)
    with op.batch_alter_table('catalog_offers') as batch:
        batch.drop_index('ix_catalog_offers_shared_status')
        batch.drop_column('shared')
