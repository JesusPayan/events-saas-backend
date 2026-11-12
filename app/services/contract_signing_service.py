
import base64
import binascii
import hashlib
import io
import secrets
import uuid

from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.contract_signature import ContractSignature
from app.models.contract_signature_request import ContractSignatureRequest
from app.models.contract_signature_audit import ContractSignatureAudit
from app.models.contract_document import ContractDocument
from app.services.contract_document_service import (
    read_verified_document,
)
import io
import base64
from PIL import Image, ImageChops, UnidentifiedImageError
from app.services.contract_bilateral_service import (
    activate_if_both_signed
)
from app.services.contract_protection_service import assert_contract_content_editable

CONSENT_VERSION = "v1.0"
CONSENT_TEXT = (
    "Declaro que he revisado el documento contractual "
    "mostrado, que deseo firmarlo electrónicamente "
    "y que acepto utilizar mi firma dibujada como "
    "manifestación de consentimiento."
)

MAX_SIGNATURE_BYTES = 200_000


class ContractSigningError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)



def decode_signature(image_data):
    if not isinstance(image_data, str):
        raise ContractSigningError("invalid_signature", "La firma debe ser una imagen PNG.")

    prefix = "data:image/png;base64,"
    if not image_data.startswith(prefix):
        raise ContractSigningError("invalid_signature_format", "Se requiere PNG en Base64.")

    encoded = image_data[len(prefix):]
    if len(encoded) > 4 * ((MAX_SIGNATURE_BYTES + 2) // 3):
        raise ContractSigningError("signature_too_large", "La imagen excede el tamaño permitido.", 413)

    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_SIGNATURE_BYTES:
            raise ContractSigningError("signature_too_large", "La imagen excede el tamaño permitido.", 413)

        with Image.open(io.BytesIO(raw)) as img:
            if img.format != "PNG":
                raise ValueError("Formato PNG inválido")
            if not (100 <= img.width <= 2000 and 40 <= img.height <= 1000):
                raise ValueError("Dimensiones inválidas")
            img.load()
            normalized = img.convert("RGBA")

            background = Image.new("RGBA", normalized.size, (255, 255, 255, 255))
            background.alpha_composite(normalized)
            rgb = background.convert("RGB")
            white = Image.new("RGB", rgb.size, (255, 255, 255))
            difference = ImageChops.difference(rgb, white)
            if difference.getbbox() is None:
                raise ValueError("Firma vacía")

            output = io.BytesIO()
            normalized.save(output, format="PNG")
            return output.getvalue()

    except ContractSigningError:
        raise
    except (ValueError, binascii.Error, UnidentifiedImageError, OSError, TypeError) as exc:
        raise ContractSigningError("invalid_signature", "La imagen de firma no es válida.") from exc


def register_contract_signature(
    *,
    token,
    signature_data,
    consent_accepted,
    signer_name,
    ip_address=None,
    user_agent=None,
):
    if not isinstance(token, str) or not (32 <= len(token) <= 256):
        raise ContractSigningError(
            "invalid_invitation",
            "Invitación inválida.",
            404,
        )

    if consent_accepted is not True:
        raise ContractSigningError(
            "consent_required",
            "Debes aceptar expresamente el consentimiento.",
        )

    if not isinstance(signer_name, str) or not signer_name.strip():
        raise ContractSigningError(
            "signer_name_required",
            "El nombre del firmante es obligatorio.",
        )

    if len(signer_name.strip()) > 200:
        raise ContractSigningError(
            "invalid_signer_name",
            "El nombre es demasiado largo.",
        )

    image_bytes = decode_signature(signature_data)
    signature_hash = hashlib.sha256(image_bytes).hexdigest()

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    stored_file = None

    try:
        invitation = db.session.scalar(
            select(ContractSignatureRequest)
            .where(
                ContractSignatureRequest.token_hash == token_hash
            )
            .with_for_update()
        )

        if invitation is None:
            raise ContractSigningError(
                "invalid_invitation",
                "Invitación inválida.",
                404,
            )

        now = utc_now()

        if invitation.status != "verified":
            raise ContractSigningError(
                "invitation_not_verified",
                "La invitación no está verificada.",
                409,
            )

        if invitation.expires_at <= now or invitation.revoked_at:
            raise ContractSigningError(
                "invitation_expired",
                "La invitación expiró o fue revocada.",
                410,
            )

        if invitation.verified_at is None:
            raise ContractSigningError(
                "otp_verification_required",
                "Debes verificar tu correo antes de firmar.",
                409,
            )

        existing = db.session.scalar(
            select(ContractSignature.id)
            .where(
                ContractSignature.tenant_id == invitation.tenant_id,
                ContractSignature.request_id == invitation.id,
            )
        )

        if existing is not None:
            raise ContractSigningError(
                "already_signed",
                "Esta invitación ya fue firmada.",
                409,
            )

        document = db.session.scalar(
            select(ContractDocument)
            .where(
                ContractDocument.id == invitation.document_id,
                ContractDocument.tenant_id == invitation.tenant_id,
                ContractDocument.contract_id == invitation.contract_id,
            )
        )

        if document is None or not document.is_final:
            raise ContractSigningError(
                "document_not_final",
                "El documento no está disponible para firma.",
                409,
            )

        # Comprueba el PDF físico contra su hash y tamaño.
        read_verified_document(document)

        root_config = current_app.config.get(
            "CONTRACT_SIGNATURE_STORAGE_ROOT"
        )

        if not root_config:
            raise RuntimeError(
                "CONTRACT_SIGNATURE_STORAGE_ROOT no configurado"
            )

        root = Path(root_config).resolve()

        storage_key = (
            f"tenants/{invitation.tenant_id}/"
            f"contracts/{invitation.contract_id}/"
            f"{uuid.uuid4().hex}.png"
        )

        destination = (root / storage_key).resolve()

        if not destination.is_relative_to(root):
            raise RuntimeError("Ruta de firma inválida")

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with destination.open("xb") as output:
            stored_file = destination
            output.write(image_bytes)

        signature = ContractSignature(
            tenant_id=invitation.tenant_id,
            request_id=invitation.id,
            document_id=document.id,
            signer_name=signer_name.strip(),
            signature_storage_key=storage_key,
            signature_sha256=signature_hash,
            document_sha256=document.sha256,
            consent_text=CONSENT_TEXT,
            consent_version=CONSENT_VERSION,
            consent_accepted_at=now,
            signed_at=now,
            ip_address=(ip_address or "")[:45] or None,
            user_agent=(user_agent or "")[:512] or None,
        )

        db.session.add(signature)
        db.session.flush()

        invitation.status = "signed"
        invitation.signed_at = now

        audit = ContractSignatureAudit(
            tenant_id=invitation.tenant_id,
            request_id=invitation.id,
            event_type="contract_signed",
            actor_type="signer",
            actor_user_id=None,
            ip_address=(ip_address or "")[:45] or None,
            user_agent=(user_agent or "")[:512] or None,
            metadata_json={
                "signature_id": signature.id,
                "document_id": document.id,
                "document_version": document.version,
                "document_sha256": document.sha256,
                "signature_sha256": signature_hash,
                "consent_version": CONSENT_VERSION,
            },
        )

        db.session.add(audit)
        db.session.flush()
        activated = activate_if_both_signed(
            tenant_id=invitation.tenant_id,
            contract_id=invitation.contract_id,
            document_id=document.id,
            actor_user_id=invitation.created_by,
        )
        current_app.logger.info(
            "Activación bilateral: contrato=%s documento=%s activated=%s",
            invitation.contract_id,
            document.id,
            activated,
        )
        from app.services.contract_protection_service import (
    assert_contract_content_editable,
)

        assert_contract_content_editable(
            tenant_id=tenant_id,
            contract_id=contract_id,
        )

        db.session.commit()

        return {
             "signature_id": signature.id,
             "request_id": invitation.id,
             "document_id": document.id,
             "status": "signed",
             "signed_at": now.isoformat() + "Z",
             "contract_activated": activated,
        }

    except ContractSigningError:
        db.session.rollback()
        if stored_file:
            stored_file.unlink(missing_ok=True)
        raise

    except IntegrityError as exc:
        db.session.rollback()
        if stored_file:
            stored_file.unlink(missing_ok=True)
        raise ContractSigningError(
            "signature_conflict",
            "La firma ya fue registrada o existe un conflicto.",
            409,
        ) from exc

    except Exception:
        db.session.rollback()
        if stored_file:
            stored_file.unlink(missing_ok=True)
        raise
