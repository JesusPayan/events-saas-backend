from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, CheckConstraint

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ContractSignature(db.Model):
    __tablename__ = "contract_signatures"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    request_id = db.Column(db.BigInteger, nullable=False)
    document_id = db.Column(db.BigInteger, nullable=False)
    signer_name = db.Column(db.String(200), nullable=False)
    signature_storage_key = db.Column(db.String(500), nullable=False)
    signature_sha256 = db.Column(db.String(64), nullable=False)
    document_sha256 = db.Column(db.String(64), nullable=False)
    consent_text = db.Column(db.Text, nullable=False)
    consent_version = db.Column(db.String(40), nullable=False)
    consent_accepted_at = db.Column(db.DateTime, nullable=False)
    signed_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contract_signatures_tenant_id"),
        UniqueConstraint("tenant_id", "request_id", name="uq_contract_signatures_request"),
        ForeignKeyConstraint(["tenant_id", "request_id"], ["contract_signature_requests.tenant_id", "contract_signature_requests.id"], name="fk_contract_signatures_request"),
        ForeignKeyConstraint(["tenant_id", "document_id"], ["contract_documents.tenant_id", "contract_documents.id"], name="fk_contract_signatures_document"),
        db.Index("ix_contract_signatures_document", "tenant_id", "document_id"),
    )
