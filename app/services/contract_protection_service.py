
"""COM-02.1.10 - Protección de contratos y documentos firmados."""

from sqlalchemy import select, exists
from app.extensions import db
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.contract_signature import ContractSignature
from app.models.contract_signature_request import ContractSignatureRequest


class ContractProtectedError(Exception):
    def __init__(self, message, code="contract_protected"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = 409


def lock_contract(*, tenant_id: int, contract_id: int) -> Contract:
    """Bloquea la fila del contrato durante la transacción."""
    contract = db.session.scalar(
        select(Contract)
        .where(
            Contract.tenant_id == tenant_id,
            Contract.id == contract_id,
        )
        .with_for_update()
    )

    if contract is None:
        raise LookupError("Contrato no encontrado.")

    return contract


def has_registered_signatures(*, tenant_id: int, contract_id: int) -> bool:
    """Consulta firmas reales, independientemente del estado de la invitación."""
    query = (
        select(ContractSignature.id)
        .join(
            ContractSignatureRequest,
            (ContractSignatureRequest.tenant_id == ContractSignature.tenant_id)
            & (ContractSignatureRequest.id == ContractSignature.request_id),
        )
        .where(
            ContractSignatureRequest.tenant_id == tenant_id,
            ContractSignatureRequest.contract_id == contract_id,
        )
        .limit(1)
    )
    return db.session.scalar(query) is not None


def has_final_document(*, tenant_id: int, contract_id: int) -> bool:
    query = (
        select(ContractDocument.id)
        .where(
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.is_final.is_(True),
        )
        .limit(1)
    )
    return db.session.scalar(query) is not None


def assert_contract_content_editable(*, tenant_id: int, contract_id: int) -> Contract:
    """Prohíbe editar contenido contractual después de cerrar el PDF final."""
    contract = lock_contract(
        tenant_id=tenant_id,
        contract_id=contract_id,
    )

    if contract.status != "draft":
        raise ContractProtectedError(
            "El contrato ya no está en borrador y no puede modificarse."
        )

    if has_final_document(tenant_id=tenant_id, contract_id=contract_id):
        raise ContractProtectedError(
            "El contrato tiene un documento final. "
            "No se permite modificar su contenido."
        )

    if has_registered_signatures(tenant_id=tenant_id, contract_id=contract_id):
        raise ContractProtectedError(
            "El contrato ya tiene firmas registradas."
        )

    return contract


def assert_document_can_be_modified(*, tenant_id: int, document_id: int) -> ContractDocument:
    """Bloquea alteraciones de documentos finales o con firmas."""
    document = db.session.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.id == document_id,
        )
        .with_for_update()
    )

    if document is None:
        raise LookupError("Documento no encontrado.")

    contract = lock_contract(
        tenant_id=tenant_id,
        contract_id=document.contract_id,
    )

    if contract.status != "draft" or document.is_final:
        raise ContractProtectedError(
            "No se permite modificar un documento final o de un contrato cerrado.",
            "document_protected",
        )

    signed = db.session.scalar(
        select(ContractSignature.id)
        .where(
            ContractSignature.tenant_id == tenant_id,
            ContractSignature.document_id == document_id,
        )
        .limit(1)
    )

    if signed is not None:
        raise ContractProtectedError(
            "El documento contiene firmas y no puede modificarse.",
            "document_signed",
        )

    return document


def assert_new_invitation_allowed(
    *,
    tenant_id: int,
    contract_id: int,
    document_id: int,
    signer_role: str,
) -> None:
    """Impide nuevas invitaciones para roles que ya firmaron."""
    if signer_role not in ("client", "provider"):
        raise ValueError("Rol de firmante inválido.")

    contract = lock_contract(
        tenant_id=tenant_id,
        contract_id=contract_id,
    )

    if contract.status != "draft":
        raise ContractProtectedError(
            "No se pueden crear invitaciones para un contrato que ya no está en borrador."
        )

    document = db.session.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.id == document_id,
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.is_final.is_(True),
        )
    )

    if document is None:
        raise ContractProtectedError(
            "La invitación requiere un documento final del contrato.",
            "invalid_signing_document",
        )

    latest_final = db.session.scalar(
        select(ContractDocument.id)
        .where(
            ContractDocument.tenant_id == tenant_id,
            ContractDocument.contract_id == contract_id,
            ContractDocument.is_final.is_(True),
        )
        .order_by(ContractDocument.version.desc())
        .limit(1)
    )

    if latest_final != document_id:
        raise ContractProtectedError(
            "Solo se permite firmar la última versión final.",
            "obsolete_document",
        )
    active_invitation = db.session.scalar(
        select(ContractSignatureRequest.id)
        .where(
            ContractSignatureRequest.tenant_id == tenant_id,
            ContractSignatureRequest.contract_id == contract_id,
            ContractSignatureRequest.document_id == document_id,
            ContractSignatureRequest.signer_role == signer_role,
            ContractSignatureRequest.status.in_(
                ("pending", "verified")
            ),
            ContractSignatureRequest.revoked_at.is_(None),
            ContractSignatureRequest.expires_at > db.func.utc_timestamp(),
        )
        .limit(1)
    )

    if active_invitation is not None:
        raise ContractProtectedError(
            "Ya existe una invitación vigente para este firmante.",
            "active_invitation_exists",
        )

    already_signed = db.session.scalar(
        select(ContractSignature.id)
        .join(
            ContractSignatureRequest,
            (ContractSignatureRequest.tenant_id == ContractSignature.tenant_id)
            & (ContractSignatureRequest.id == ContractSignature.request_id),
        )
        .where(
            ContractSignatureRequest.tenant_id == tenant_id,
            ContractSignatureRequest.contract_id == contract_id,
            ContractSignatureRequest.signer_role == signer_role,
        )
        .limit(1)
    )

    if already_signed is not None:
        raise ContractProtectedError(
            "Ya existe una firma registrada para este rol.",
            "signer_already_signed",
        )
