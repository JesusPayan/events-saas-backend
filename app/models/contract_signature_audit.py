from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, CheckConstraint

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ContractSignatureAudit(db.Model):
    __tablename__ = "contract_signature_audits"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    request_id = db.Column(db.BigInteger, nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    actor_type = db.Column(db.String(20), nullable=False)
    actor_user_id = db.Column(db.BigInteger, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contract_sign_audits_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "request_id"], ["contract_signature_requests.tenant_id", "contract_signature_requests.id"], name="fk_contract_sign_audits_request"),
        ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_contract_sign_audits_actor"),
        CheckConstraint("actor_type IN ('user', 'signer', 'system')", name="ck_contract_sign_audits_actor"),
        db.Index("ix_contract_sign_audits_request", "tenant_id", "request_id", "created_at"),
    )
