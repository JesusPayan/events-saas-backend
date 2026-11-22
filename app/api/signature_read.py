"""Rutas públicas para lectura de invitación y PDF; no exponen storage_key ni email."""
import hashlib
from datetime import datetime, timezone
from io import BytesIO

from flask import Blueprint, jsonify, send_file
from sqlalchemy import select

from app.extensions import db
from app.models.contract_signature_request import ContractSignatureRequest
from app.models.contract_document import ContractDocument
from app.services.contract_document_service import read_verified_document, ContractDocumentError

bp = Blueprint('signature_read', __name__)


def invitation_for_token(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        return None
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    return db.session.scalar(select(ContractSignatureRequest).where(
        ContractSignatureRequest.token_hash == digest
    ))


def current_invitation(token):
    invitation = invitation_for_token(token)
    if invitation is None:
        return None, (jsonify(error='invalid_invitation'), 404)
    if invitation.status in ('revoked', 'expired') or invitation.revoked_at is not None or invitation.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        return None, (jsonify(error='invitation_unavailable'), 410)
    return invitation, None


def final_document(invitation):
    return db.session.scalar(select(ContractDocument).where(
        ContractDocument.id == invitation.document_id,
        ContractDocument.tenant_id == invitation.tenant_id,
        ContractDocument.contract_id == invitation.contract_id,
        ContractDocument.is_final.is_(True),
    ))


@bp.get('/signatures/invitations/<token>')
def invitation_details(token):
    invitation, error = current_invitation(token)
    if error is not None:
        return error
    document = final_document(invitation)
    if document is None:
        return jsonify(error='document_not_found'), 404
    response = jsonify(
        request_id=invitation.id,
        contract_id=invitation.contract_id,
        document_id=document.id,
        document_version=document.version,
        signer_name=invitation.signer_name,
        signer_role=invitation.signer_role,
        status=invitation.status,
        expires_at=invitation.expires_at.isoformat() + 'Z',
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@bp.get('/signatures/invitations/<token>/document')
def invitation_document(token):
    invitation, error = current_invitation(token)
    if error is not None:
        return error
    document = final_document(invitation)
    if document is None:
        return jsonify(error='document_not_found'), 404
    try:
        data = read_verified_document(document)
    except ContractDocumentError:
        return jsonify(error='document_unavailable'), 409
    response = send_file(
        BytesIO(data), mimetype='application/pdf',
        as_attachment=False, download_name=f'contrato-v{document.version}.pdf',
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
