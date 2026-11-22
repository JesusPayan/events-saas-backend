"""COM-02.1.1: contract electronic signing foundation

Revision ID: 6c0211000001
Revises: 49decfb649f6
"""
from alembic import op
import sqlalchemy as sa

revision = "6c0211000001"
down_revision = "49decfb649f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False, server_default="application/pdf"),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contract_documents_tenant_id"),
        sa.UniqueConstraint("tenant_id", "contract_id", "version", name="uq_contract_documents_version"),
        sa.ForeignKeyConstraint(["tenant_id", "contract_id"], ["contracts.tenant_id", "contracts.id"], name="fk_contract_documents_contract"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_contract_documents_user"),
        sa.CheckConstraint("version > 0 AND byte_size > 0", name="ck_contract_documents_positive"),
    )
    op.create_index("ix_contract_documents_contract", "contract_documents", ["tenant_id", "contract_id"])

    op.create_table(
        "contract_signature_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("signer_role", sa.String(20), nullable=False),
        sa.Column("signer_name", sa.String(200), nullable=False),
        sa.Column("signer_email", sa.String(254), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("signed_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contract_sign_requests_tenant_id"),
        sa.UniqueConstraint("token_hash", name="uq_contract_sign_requests_token_hash"),
        sa.ForeignKeyConstraint(["tenant_id", "contract_id"], ["contracts.tenant_id", "contracts.id"], name="fk_contract_sign_requests_contract"),
        sa.ForeignKeyConstraint(["tenant_id", "document_id"], ["contract_documents.tenant_id", "contract_documents.id"], name="fk_contract_sign_requests_document"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_contract_sign_requests_user"),
        sa.CheckConstraint("signer_role IN ('client', 'provider')", name="ck_contract_sign_requests_role"),
        sa.CheckConstraint("status IN ('pending', 'verified', 'signed', 'expired', 'revoked')", name="ck_contract_sign_requests_status"),
    )
    op.create_index("ix_contract_sign_requests_contract", "contract_signature_requests", ["tenant_id", "contract_id"])
    op.create_index("ix_contract_sign_requests_expiry", "contract_signature_requests", ["status", "expires_at"])

    op.create_table(
        "contract_signature_otps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contract_sign_otps_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "request_id"], ["contract_signature_requests.tenant_id", "contract_signature_requests.id"], name="fk_contract_sign_otps_request"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts", name="ck_contract_sign_otps_attempts"),
    )
    op.create_index("ix_contract_sign_otps_request", "contract_signature_otps", ["tenant_id", "request_id"])

    op.create_table(
        "contract_signatures",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("signer_name", sa.String(200), nullable=False),
        sa.Column("signature_storage_key", sa.String(500), nullable=False),
        sa.Column("signature_sha256", sa.String(64), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("consent_text", sa.Text(), nullable=False),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("consent_accepted_at", sa.DateTime(), nullable=False),
        sa.Column("signed_at", sa.DateTime(), nullable=False),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contract_signatures_tenant_id"),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_contract_signatures_request"),
        sa.ForeignKeyConstraint(["tenant_id", "request_id"], ["contract_signature_requests.tenant_id", "contract_signature_requests.id"], name="fk_contract_signatures_request"),
        sa.ForeignKeyConstraint(["tenant_id", "document_id"], ["contract_documents.tenant_id", "contract_documents.id"], name="fk_contract_signatures_document"),
    )
    op.create_index("ix_contract_signatures_document", "contract_signatures", ["tenant_id", "document_id"])

    op.create_table(
        "contract_signature_audits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger()),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contract_sign_audits_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "request_id"], ["contract_signature_requests.tenant_id", "contract_signature_requests.id"], name="fk_contract_sign_audits_request"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_contract_sign_audits_actor"),
        sa.CheckConstraint("actor_type IN ('user', 'signer', 'system')", name="ck_contract_sign_audits_actor"),
    )
    op.create_index("ix_contract_sign_audits_request", "contract_signature_audits", ["tenant_id", "request_id", "created_at"])


def downgrade():
    for table, index in [
        ("contract_signature_audits", "ix_contract_sign_audits_request"),
        ("contract_signatures", "ix_contract_signatures_document"),
        ("contract_signature_otps", "ix_contract_sign_otps_request"),
        ("contract_signature_requests", "ix_contract_sign_requests_expiry"),
        ("contract_signature_requests", "ix_contract_sign_requests_contract"),
        ("contract_documents", "ix_contract_documents_contract"),
    ]:
        op.drop_index(index, table_name=table)
    for table in ["contract_signature_audits", "contract_signatures", "contract_signature_otps", "contract_signature_requests", "contract_documents"]:
        op.drop_table(table)
