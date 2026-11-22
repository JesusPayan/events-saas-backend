"""COM-03.5 company settings and immutable issued receipts.

Revision ID: c03500000001
Revises: 9bb5c58fb617
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMBLOB

revision = 'c03500000001'
down_revision = '9bb5c58fb617'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('company_receipt_settings',
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id'), primary_key=True),
        sa.Column('commercial_name', sa.String(180)),
        sa.Column('contact_email', sa.String(254)),
        sa.Column('phone', sa.String(40)),
        sa.Column('address', sa.String(500)),
        sa.Column('tax_id', sa.String(20)),
        sa.Column('timezone', sa.String(64), nullable=False, server_default='America/Mazatlan'),
        sa.Column('logo_mime', sa.String(20)),
        sa.Column('logo_bytes', sa.LargeBinary().with_variant(MEDIUMBLOB(), 'mysql')),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_table('issued_payment_receipts',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False),
        sa.Column('contract_id', sa.BigInteger(), nullable=False),
        sa.Column('payment_id', sa.BigInteger(), nullable=False),
        sa.Column('folio', sa.String(32), nullable=False, unique=True),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('pdf_bytes', MEDIUMBLOB().with_variant(sa.LargeBinary(), 'sqlite'), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'payment_id', name='uq_issued_receipt_tenant_payment'),
        sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['contract_payments.tenant_id', 'contract_payments.id'], name='fk_issued_receipt_payment'),
        sa.ForeignKeyConstraint(['tenant_id', 'contract_id'], ['contracts.tenant_id', 'contracts.id'], name='fk_issued_receipt_contract'),
    )


def downgrade():
    # A downgrade would destroy immutable issued documents: explicit backup required.
    raise RuntimeError('Downgrade destructivo bloqueado: conservar comprobantes emitidos')
