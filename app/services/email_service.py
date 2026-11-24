
"""Reusable SMTP email delivery for the EasiAcc platform."""
from app.branding import BRAND_NAME

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    pass


def send_email(*, to_email: str, subject: str, text_body: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    sender_name = os.environ.get("SMTP_FROM_NAME", BRAND_NAME)
    mode = os.environ.get("SMTP_SECURITY", "starttls").strip().lower()

    if mode not in ("none", "starttls", "ssl"):
        raise EmailDeliveryError(
            "SMTP_SECURITY debe ser none, starttls o ssl"
        )

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as exc:
        raise EmailDeliveryError("SMTP_PORT inválido") from exc

    if not 1 <= port <= 65535:
        raise EmailDeliveryError("SMTP_PORT fuera de rango")

    if not host or not sender:
        raise EmailDeliveryError(
            "SMTP_HOST y SMTP_FROM_EMAIL son obligatorios"
        )

    if mode == "none":
        # Evitar SMTP sin cifrado fuera del entorno de pruebas.
        environment = os.environ.get("FLASK_ENV", "").lower()

        if environment != "test" or host not in (
            "127.0.0.1", "localhost", "::1"
        ):
            raise EmailDeliveryError(
                "SMTP sin cifrado solo permitido en pruebas locales"
            )
    elif not username or not password:
        raise EmailDeliveryError(
            "SMTP_USERNAME y SMTP_PASSWORD son obligatorios"
        )

    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)

    try:
        if mode == "ssl":
            context = ssl.create_default_context()

            with smtplib.SMTP_SSL(
                host, port, timeout=15, context=context
            ) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)

        elif mode == "starttls":
            context = ssl.create_default_context()

            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(msg)

        else:
            # Mailpit local: sin TLS ni autenticación.
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.send_message(msg)

    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Error de entrega SMTP")
        raise EmailDeliveryError(
            "No se pudo entregar el correo"
        ) from exc


def send_signature_otp(to_email: str, code: str) -> None:
    send_email(
        to_email=to_email,
        subject="Código de verificación para firmar tu contrato",
        text_body=(
            "Recibimos una solicitud para firmar electrónicamente un contrato.\n\n"
            f"Tu código de verificación es: {code}\n\n"
            "Este código vence en 5 minutos. No lo compartas.\n"
            "Si no solicitaste esta verificación, ignora este mensaje.\n\n"
            f"Firma electrónica por {BRAND_NAME}"
        ),
    )
