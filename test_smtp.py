
import os
import ssl
import smtplib

from dotenv import load_dotenv, dotenv_values

load_dotenv(override=True)
config = dotenv_values(".env")
username = os.getenv("SMTP_USERNAME", "").strip()
password = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
print("Usuario utilizado:", username)
print("Coincide con .env:", username == config.get("SMTP_USERNAME"))
print("Contraseña configurada:", bool(password))
print("Longitud de contraseña:", len(password))
print(
    "Contraseña coincide con .env:",
    password == (config.get("SMTP_PASSWORD") or "").replace(" ", "")
)

if not username or not password:
    raise RuntimeError("Faltan credenciales SMTP")

try:
    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        timeout=30,
        context=ssl.create_default_context(),
    ) as smtp:

        smtp.ehlo()

        print("SSL: OK")
        print("AUTH LOGIN disponible:",
              "LOGIN" in smtp.esmtp_features.get(
                  "auth", ""
              ).upper().split())

        smtp.auth(
    "PLAIN",
    lambda challenge=None: (
        f"\0{username}\0{password}"
    ),
)

        print("AUTENTICACIÓN EXITOSA")

except smtplib.SMTPAuthenticationError as exc:
    print("Gmail rechazó la autenticación.")
    print("Código SMTP:", exc.smtp_code)

except smtplib.SMTPServerDisconnected:
    print("La conexión se cerró durante AUTH LOGIN.")

except Exception as exc:
    print("Error:", type(exc).__name__)
    print(str(exc))
