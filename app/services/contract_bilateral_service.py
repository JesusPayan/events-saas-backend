"""COM-02.1.9: activación bilateral en la MISMA transacción de firma.

No hace commit: el llamador debe confirmar la transacción.
"""
from datetime import datetime, timezone
from sqlalchemy import select
from app.extensions import db
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.contract_signature import ContractSignature
from app.models.contract_signature_request import ContractSignatureRequest
from app.models.contract_status_history import ContractStatusHistory


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def activate_if_both_signed(*, tenant_id: int, contract_id: int, document_id: int, actor_user_id: int) -> bool:
    """True solo si esta llamada cambia draft -> active; False en otro caso.

    Invocar después de insertar ContractSignature y actualizar la solicitud a signed,
    antes del db.session.commit() de la firma.
    """
    contract = db.session.scalar(
        select(Contract).where(Contract.id == contract_id, Contract.tenant_id == tenant_id)
        .with_for_update()
    )
    if contract is None:
        raise ValueError('Contrato inexistente en el tenant')
    if contract.status != 'draft':
        return False

    document = db.session.scalar(
        select(ContractDocument).where(
            ContractDocument.id == document_id,
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.is_final.is_(True),
        )
    )
    if document is None:
        return False

    # Solo se activa la última versión final del contrato.
    newest_final = db.session.scalar(
        select(ContractDocument.version).where(
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.is_final.is_(True),
        ).order_by(ContractDocument.version.desc()).limit(1)
    )
    if newest_final != document.version:
        return False

    # Requiere firmas materializadas, no solo un estado 'signed'.
    signed_roles = set(db.session.scalars(
        select(ContractSignatureRequest.signer_role)
        .join(ContractSignature, (
            (ContractSignature.tenant_id == ContractSignatureRequest.tenant_id) &
            (ContractSignature.request_id == ContractSignatureRequest.id) &
            (ContractSignature.document_id == ContractSignatureRequest.document_id)
        ))
        .where(
            ContractSignatureRequest.tenant_id == tenant_id,
            ContractSignatureRequest.contract_id == contract_id,
            ContractSignatureRequest.document_id == document_id,
            ContractSignatureRequest.status == 'signed',
            ContractSignatureRequest.revoked_at.is_(None),
            ContractSignature.document_sha256 == document.sha256,
        )
    ).all())

    if not {'client', 'provider'}.issubset(signed_roles):
        return False

    now = utc_now()
    contract.status = 'active'
    contract.updated_at = now
    db.session.add(ContractStatusHistory(
        tenant_id=tenant_id,
        contract_id=contract_id,
        previous_status='draft',
        new_status='active',
        notes=f'Activación automática: firmas client y provider del documento #{document_id}, versión {document.version}.',
        changed_by=actor_user_id,
        created_at=now,
    ))
    return True
