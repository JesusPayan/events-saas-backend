from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, CheckConstraint

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ContractDocument(db.Model):
    __tablename__ = "contract_documents"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    contract_id = db.Column(db.BigInteger, nullable=False)
    version = db.Column(db.Integer, nullable=False)
    storage_key = db.Column(db.String(500), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    byte_size = db.Column(db.BigInteger, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False, default="application/pdf")
    is_final = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contract_documents_tenant_id"),
        UniqueConstraint("tenant_id", "contract_id", "version", name="uq_contract_documents_version"),
        ForeignKeyConstraint(["tenant_id", "contract_id"], ["contracts.tenant_id", "contracts.id"], name="fk_contract_documents_contract"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_contract_documents_user"),
        CheckConstraint("version > 0 AND byte_size > 0", name="ck_contract_documents_positive"),
        db.Index("ix_contract_documents_contract", "tenant_id", "contract_id"),
    )
