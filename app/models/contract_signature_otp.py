from datetime import datetime, timezone
from app.extensions import db
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, CheckConstraint

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class ContractSignatureOtp(db.Model):
    __tablename__ = "contract_signature_otps"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.BigInteger, nullable=False)
    request_id = db.Column(db.BigInteger, nullable=False)
    code_hash = db.Column(db.String(128), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contract_sign_otps_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "request_id"], ["contract_signature_requests.tenant_id", "contract_signature_requests.id"], name="fk_contract_sign_otps_request"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts", name="ck_contract_sign_otps_attempts"),
        db.Index("ix_contract_sign_otps_request", "tenant_id", "request_id"),
    )
