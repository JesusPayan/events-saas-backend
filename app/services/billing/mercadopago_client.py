
"""Cliente HTTP de Mercado Pago.

No registra tokens, payloads ni datos personales.
Las llamadas de red deben simularse en pruebas unitarias.
"""

import json
import logging
import urllib.error
import urllib.request

from flask import current_app

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 1024 * 1024


class MPError(Exception):
    def __init__(self, code, *, status_code=None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def api(method, path, payload=None, *, idempotency_key=None):
    token = current_app.config.get("MP_ACCESS_TOKEN")

    if not token:
        raise MPError("mercadopago_not_configured")

    if not path.startswith("/") or "://" in path:
        raise MPError("invalid_api_path")

    data = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else None
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    if data is not None:
        headers["Content-Type"] = "application/json"

    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    request = urllib.request.Request(
        "https://api.mercadopago.com" + path,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)

            if len(raw) > MAX_RESPONSE_BYTES:
                raise MPError("mercadopago_response_too_large")

            return json.loads(raw)

    except urllib.error.HTTPError as exc:
        status = exc.code

        if status in (401, 403):
            code = "mercadopago_auth_error"
        elif status == 404:
            code = "mercadopago_resource_not_found"
        elif status == 429:
            code = "mercadopago_rate_limited"
        elif status >= 500:
            code = "mercadopago_server_error"
        else:
            code = "mercadopago_http_error"

        logger.warning(
            "Mercado Pago HTTP error: method=%s status=%s code=%s",
            method,
            status,
            code,
        )

        raise MPError(code, status_code=status) from exc

    except urllib.error.URLError as exc:
        logger.warning(
            "Mercado Pago connection error: method=%s",
            method,
        )
        raise MPError("mercadopago_connection_error") from exc

    except (ValueError, UnicodeError) as exc:
        logger.warning(
            "Mercado Pago invalid JSON response: method=%s",
            method,
        )
        raise MPError("mercadopago_invalid_response") from exc
