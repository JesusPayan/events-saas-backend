"""COM-02.1.10: consultas administrativas y descarga verificada por tenant."""

from io import BytesIO

from flask import Blueprint, current_app, g, jsonify, send_file
from sqlalchemy import select

from app.extensions import db
from app.security import tenant_permission
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.contract_signature_request import ContractSignatureRequest
from app.models.contract_signature import ContractSignature
from app.models.contract_signature_audit import ContractSignatureAudit
from app.services.contract_document_service import (
    ContractDocumentError,
    read_verified_document,
)

bp = Blueprint("contract_signature_admin", __name__)


def iso(value):
    return value.isoformat() + "Z" if value else None


@bp.get("/contracts/<int:contract_id>/signature-management")
@tenant_permission("contracts.read")
def signature_management(contract_id):
    contract = db.session.scalar(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.tenant_id == g.tenant_id,
        )
    )
    if contract is None:
        return jsonify(error="contract_not_found"), 404

    documents = db.session.scalars(
        select(ContractDocument)
        .where(
            ContractDocument.tenant_id == g.tenant_id,
            ContractDocument.contract_id == contract_id,
        )
        .order_by(ContractDocument.version.desc())
    ).all()

    requests = db.session.scalars(
        select(ContractSignatureRequest)
        .where(
            ContractSignatureRequest.tenant_id == g.tenant_id,
            ContractSignatureRequest.contract_id == contract_id,
        )
        .order_by(
            ContractSignatureRequest.created_at.desc(),
            ContractSignatureRequest.id.desc(),
        )
    ).all()

    ids = [r.id for r in requests]
    signatures = (
        db.session.scalars(
            select(ContractSignature).where(
                ContractSignature.tenant_id == g.tenant_id,
                ContractSignature.request_id.in_(ids),
            )
        ).all()
        if ids else []
    )
    audits = (
        db.session.scalars(
            select(ContractSignatureAudit)
            .where(
                ContractSignatureAudit.tenant_id == g.tenant_id,
                ContractSignatureAudit.request_id.in_(ids),
            )
            .order_by(
                ContractSignatureAudit.created_at.desc(),
                ContractSignatureAudit.id.desc(),
            )
        ).all()
        if ids else []
    )

    by_request = {s.request_id: s for s in signatures}
    response = jsonify(
        contract={
            "id": contract.id,
            "contract_number": contract.contract_number,
            "status": contract.status,
        },
        documents=[
            {
                "id": d.id,
                "version": d.version,
                "is_final": d.is_final,
                "sha256": d.sha256,
                "created_at": iso(d.created_at),
            }
            for d in documents
        ],
        invitations=[
            {
                "id": r.id,
                "document_id": r.document_id,
                "signer_name": r.signer_name,
                "signer_email": r.signer_email,
                "signer_role": r.signer_role,
                "status": r.status,
                "created_at": iso(r.created_at),
                "expires_at": iso(r.expires_at),
                "verified_at": iso(r.verified_at),
                "signed_at": iso(r.signed_at),
                "revoked_at": iso(r.revoked_at),
                "signature": (
                    {
                        "id": by_request[r.id].id,
                        "signed_at": iso(by_request[r.id].signed_at),
                        "signature_sha256": by_request[r.id].signature_sha256,
                        "document_sha256": by_request[r.id].document_sha256,
                    }
                    if r.id in by_request else None
                ),
            }
            for r in requests
        ],
        audits=[
            {
                "id": a.id,
                "request_id": a.request_id,
                "event_type": a.event_type,
                "actor_type": a.actor_type,
                "actor_user_id": a.actor_user_id,
                "created_at": iso(a.created_at),
                "metadata_json": a.metadata_json,
            }
            for a in audits
        ],
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get(
    "/contracts/<int:contract_id>/signature-management/"
    "documents/<int:document_id>/pdf"
)
@tenant_permission("contracts.read")
def download_document(contract_id, document_id):
    document = db.session.scalar(
        select(ContractDocument).where(
            ContractDocument.tenant_id == g.tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.id == document_id,
        )
    )
    if document is None:
        return jsonify(error="document_not_found"), 404

    try:
        content = read_verified_document(document)
    except ContractDocumentError as exc:
        current_app.logger.warning(
            "Verificación fallida del documento %s del contrato %s: %s",
            document_id,
            contract_id,
            exc.code,
        )
        return jsonify(error=exc.code, message=exc.message), exc.status_code

    response = send_file(
        BytesIO(content),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"contrato-{contract_id}-version-{document.version}.pdf",
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
