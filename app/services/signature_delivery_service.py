"""COM-02.1.4: invitations and OTP, local MVP. UTC naive dates match existing models."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import current_app
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.contract import Contract
from app.models.contract_document import ContractDocument
from app.models.contract_signature_request import ContractSignatureRequest
from app.models.contract_signature_otp import ContractSignatureOtp
from app.services.contract_document_service import read_verified_document
from app.services.email_service import send_email, send_signature_otp, EmailDeliveryError
from app.services.contract_protection_service import (
    ContractProtectedError,
    assert_new_invitation_allowed,
)

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SignatureDeliveryError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def token_digest(token):
    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        raise SignatureDeliveryError('invalid_invitation', 'Invitación inválida.', 404)
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def otp_digest(request_id, code):
    secret = current_app.config.get('SIGNATURE_OTP_SECRET')
    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError('SIGNATURE_OTP_SECRET debe configurarse con al menos 32 caracteres aleatorios')
    return hmac.new(secret.encode('utf-8'), f'{request_id}:{code}'.encode('utf-8'), hashlib.sha256).hexdigest()


def invitation_for_update(token):
    invitation = db.session.scalar(select(ContractSignatureRequest).where(
        ContractSignatureRequest.token_hash == token_digest(token)
    ).with_for_update())
    if invitation is None:
        raise SignatureDeliveryError('invalid_invitation', 'Invitación inválida.', 404)
    if invitation.status not in ('pending', 'verified') or invitation.revoked_at is not None:
        raise SignatureDeliveryError('invitation_unavailable', 'Invitación no disponible.', 410)
    if invitation.expires_at <= now():
        invitation.status = 'expired'
        db.session.commit()
        raise SignatureDeliveryError('invitation_expired', 'La invitación ha vencido.', 410)
    return invitation



def create_and_email_invitation(
    *,
    tenant_id,
    contract_id,
    document_id,
    signer_role,
    signer_name,
    signer_email,
    created_by,
):
    if signer_role not in ("client", "provider"):
        raise SignatureDeliveryError(
            "invalid_role",
            "Rol de firmante inválido.",
        )

    if not isinstance(signer_name, str) or not 1 <= len(signer_name.strip()) <= 200:
        raise SignatureDeliveryError(
            "invalid_name",
            "Nombre de firmante inválido.",
        )

    if (
        not isinstance(signer_email, str)
        or len(signer_email.strip()) > 254
        or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+",
            signer_email.strip(),
        )
    ):
        raise SignatureDeliveryError(
            "invalid_email",
            "Correo de firmante inválido.",
        )

    if (
        isinstance(document_id, bool)
        or not isinstance(document_id, int)
        or document_id <= 0
    ):
        raise SignatureDeliveryError(
            "invalid_document_id",
            "Documento inválido.",
        )

    frontend = current_app.config.get(
        "FRONTEND_PUBLIC_URL", ""
    ).rstrip("/")

    if not frontend or not frontend.startswith(
        ("http://localhost:", "http://127.0.0.1:", "https://")
    ):
        raise RuntimeError("FRONTEND_PUBLIC_URL inválida")

    try:
        # Esta función bloquea el contrato y valida:
        # - Estado draft
        # - Documento final y última versión
        # - Ausencia de firma previa del mismo rol
        # - Ausencia de invitación vigente del mismo rol
        assert_new_invitation_allowed(
            tenant_id=tenant_id,
            contract_id=contract_id,
            document_id=document_id,
            signer_role=signer_role,
        )

        document = db.session.scalar(
            select(ContractDocument).where(
                ContractDocument.tenant_id == tenant_id,
                ContractDocument.id == document_id,
                ContractDocument.contract_id == contract_id,
                ContractDocument.is_final.is_(True),
            )
        )

        # Comprobar que el PDF físico conserva su hash.
        read_verified_document(document)

        token = secrets.token_urlsafe(32)

        inv = ContractSignatureRequest(
            tenant_id=tenant_id,
            contract_id=contract_id,
            document_id=document_id,
            signer_role=signer_role,
            signer_name=signer_name.strip(),
            signer_email=signer_email.strip().lower(),
            token_hash=token_digest(token),
            status="pending",
            expires_at=now() + timedelta(hours=72),
            created_by=created_by,
        )

        db.session.add(inv)
        db.session.commit()

        # Guardar los datos necesarios antes de enviar SMTP.
        invitation_id = inv.id
        recipient = inv.signer_email
        recipient_name = inv.signer_name

    except ContractProtectedError as exc:
        db.session.rollback()
        raise SignatureDeliveryError(
            exc.code,
            exc.message,
            409,
        ) from exc

    except Exception:
        db.session.rollback()
        raise

    url = f'{frontend}/sign/{quote(token, safe="")}'

    try:
        send_email(
            to_email=recipient,
            subject="Invitación para firmar contrato - Eventos SaaS",
            text_body=(
                f"Hola {recipient_name},\n\n"
                "Tienes un contrato pendiente de firma.\n"
                f"Accede a tu enlace privado: {url}\n\n"
                "El enlace vence en 72 horas. No lo compartas.\n"
                "Eventos SaaS"
            ),
        )

    except EmailDeliveryError as exc:
        db.session.rollback()

        try:
            saved_invitation = db.session.get(
                ContractSignatureRequest,
                invitation_id,
            )

            if (
                saved_invitation is not None
                and saved_invitation.status == "pending"
            ):
                saved_invitation.status = "revoked"
                saved_invitation.revoked_at = now()
                db.session.commit()

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "No se pudo revocar la invitación tras un fallo SMTP."
            )

        raise SignatureDeliveryError(
            "delivery_failed",
            "No se pudo enviar la invitación.",
            502,
        ) from exc

    return inv

def public_invitation(token):
    try:
        inv = invitation_for_update(token)
        doc = db.session.scalar(select(ContractDocument).where(
            ContractDocument.tenant_id == inv.tenant_id,
            ContractDocument.id == inv.document_id,
            ContractDocument.contract_id == inv.contract_id,
            ContractDocument.is_final.is_(True),
        ))
        if doc is None:
            raise SignatureDeliveryError('document_unavailable', 'Documento no disponible.', 410)
        read_verified_document(doc)
        return dict(status=inv.status, signer_name=inv.signer_name,
                    contract_id=inv.contract_id, document_version=doc.version,
                    document_sha256=doc.sha256, expires_at=inv.expires_at.isoformat() + 'Z')
    finally:
        db.session.rollback()  # Release lock; no state changes except expiry handled inside helper.


def request_otp(token):
    try:
        inv = invitation_for_update(token)
        if inv.status != 'pending':
            raise SignatureDeliveryError('already_verified', 'Invitación ya verificada.', 409)
        t = now()
        latest = db.session.scalar(select(ContractSignatureOtp).where(
            ContractSignatureOtp.tenant_id == inv.tenant_id,
            ContractSignatureOtp.request_id == inv.id,
        ).order_by(ContractSignatureOtp.created_at.desc(), ContractSignatureOtp.id.desc()).limit(1))
        if latest is not None and (t - latest.created_at).total_seconds() < 60:
            raise SignatureDeliveryError('otp_cooldown', 'Espera 60 segundos antes de reenviar.', 429)
        count = db.session.scalar(select(func.count(ContractSignatureOtp.id)).where(
            ContractSignatureOtp.tenant_id == inv.tenant_id,
            ContractSignatureOtp.request_id == inv.id,
            ContractSignatureOtp.created_at >= t - timedelta(hours=1),
        )) or 0
        if count >= 3:
            raise SignatureDeliveryError('otp_rate_limited', 'Límite de envíos por hora alcanzado.', 429)
        failed = db.session.scalar(select(func.coalesce(func.sum(ContractSignatureOtp.attempts), 0)).where(
            ContractSignatureOtp.tenant_id == inv.tenant_id,
            ContractSignatureOtp.request_id == inv.id,
        )) or 0
        if failed >= 5:
            raise SignatureDeliveryError('otp_attempts_exhausted', 'Intentos agotados para esta invitación.', 429)
        code = f'{secrets.randbelow(1_000_000):06d}'
        # Reserve code first; if SMTP fails, consume it. SMTP is not transactional.
        for old in db.session.scalars(select(ContractSignatureOtp).where(
            ContractSignatureOtp.tenant_id == inv.tenant_id,
            ContractSignatureOtp.request_id == inv.id,
            ContractSignatureOtp.consumed_at.is_(None),
        ).with_for_update()).all():
            old.consumed_at = t
        otp = ContractSignatureOtp(
            tenant_id=inv.tenant_id, request_id=inv.id, code_hash=otp_digest(inv.id, code),
            attempts=0, max_attempts=5, expires_at=t + timedelta(minutes=5), created_at=t,
        )
        db.session.add(otp)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    try:
        send_signature_otp(inv.signer_email, code)
    except EmailDeliveryError as exc:
        otp.consumed_at = now()
        db.session.commit()
        raise SignatureDeliveryError('delivery_failed', 'No se pudo enviar el código.', 502) from exc
    return {'message': 'Código enviado.', 'expires_in_seconds': 300}


def verify_otp(token, code):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise SignatureDeliveryError('invalid_otp', 'Código inválido.')
    try:
        inv = invitation_for_update(token)
        if inv.status != 'pending':
            raise SignatureDeliveryError('already_verified', 'Invitación ya verificada.', 409)
        t = now()
        total_failed = db.session.scalar(select(func.coalesce(func.sum(ContractSignatureOtp.attempts), 0)).where(
            ContractSignatureOtp.tenant_id == inv.tenant_id,
            ContractSignatureOtp.request_id == inv.id,
        )) or 0
        if total_failed >= 5:
            raise SignatureDeliveryError('otp_attempts_exhausted', 'Intentos agotados.', 429)
        otp = db.session.scalar(select(ContractSignatureOtp).where(
            ContractSignatureOtp.tenant_id == inv.tenant_id,
            ContractSignatureOtp.request_id == inv.id,
            ContractSignatureOtp.consumed_at.is_(None),
        ).order_by(ContractSignatureOtp.created_at.desc(), ContractSignatureOtp.id.desc()).limit(1).with_for_update())
        if otp is None:
            raise SignatureDeliveryError('otp_missing', 'Solicita un código nuevo.')
        if otp.expires_at <= t:
            otp.consumed_at = t
            db.session.commit()
            raise SignatureDeliveryError('otp_expired', 'Código vencido.', 410)
        if not hmac.compare_digest(otp.code_hash, otp_digest(inv.id, code)):
            otp.attempts += 1
            if otp.attempts >= otp.max_attempts or total_failed + 1 >= 5:
                otp.consumed_at = t
            db.session.commit()
            raise SignatureDeliveryError('invalid_otp', 'Código incorrecto.')
        otp.consumed_at = t
        inv.verified_at, inv.status = t, 'verified'
        db.session.commit()
        return {'verified': True, 'status': 'verified'}
    except SignatureDeliveryError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise
