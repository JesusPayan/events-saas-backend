from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy.dialects.mysql import MEDIUMBLOB


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CompanyReceiptSettings(db.Model):
    __tablename__ = 'company_receipt_settings'
    tenant_id = db.Column(db.BigInteger, db.ForeignKey('tenants.id'), primary_key=True)
    commercial_name = db.Column(db.String(180), nullable=True)
    contact_email = db.Column(db.String(254), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    tax_id = db.Column(db.String(20), nullable=True)
    timezone = db.Column(db.String(64), nullable=False, default='America/Mazatlan')
    logo_mime = db.Column(db.String(20), nullable=True)
    logo_bytes = db.Column(db.LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class IssuedPaymentReceipt(db.Model):
    __tablename__ = 'issued_payment_receipts'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    contract_id = db.Column(db.BigInteger, nullable=False)
    payment_id = db.Column(db.BigInteger, nullable=False)
    folio = db.Column(db.String(32), nullable=False, unique=True)
    sha256 = db.Column(db.String(64), nullable=False)
    pdf_bytes = db.Column(db.LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'), nullable=False)
    issued_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'payment_id', name='uq_issued_receipt_tenant_payment'),
        db.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['contract_payments.tenant_id', 'contract_payments.id'], name='fk_issued_receipt_payment'),
        db.ForeignKeyConstraint(['tenant_id', 'contract_id'], ['contracts.tenant_id', 'contracts.id'], name='fk_issued_receipt_contract'),
    )
