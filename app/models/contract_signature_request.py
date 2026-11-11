from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, CheckConstraint

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ContractSignatureRequest(db.Model):
    __tablename__ = "contract_signature_requests"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    contract_id = db.Column(db.BigInteger, nullable=False)
    document_id = db.Column(db.BigInteger, nullable=False)
    signer_role = db.Column(db.String(20), nullable=False)  # client | provider
    signer_name = db.Column(db.String(200), nullable=False)
    signer_email = db.Column(db.String(254), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    expires_at = db.Column(db.DateTime, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contract_sign_requests_tenant_id"),
        UniqueConstraint("token_hash", name="uq_contract_sign_requests_token_hash"),
        ForeignKeyConstraint(["tenant_id", "contract_id"], ["contracts.tenant_id", "contracts.id"], name="fk_contract_sign_requests_contract"),
        ForeignKeyConstraint(["tenant_id", "document_id"], ["contract_documents.tenant_id", "contract_documents.id"], name="fk_contract_sign_requests_document"),
        ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_contract_sign_requests_user"),
        CheckConstraint("signer_role IN ('client', 'provider')", name="ck_contract_sign_requests_role"),
        CheckConstraint("status IN ('pending', 'verified', 'signed', 'expired', 'revoked')", name="ck_contract_sign_requests_status"),
        db.Index("ix_contract_sign_requests_contract", "tenant_id", "contract_id"),
        db.Index("ix_contract_sign_requests_expiry", "status", "expires_at"),
    )
