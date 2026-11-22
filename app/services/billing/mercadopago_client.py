"""Mercado Pago API client. Network calls are mocked in unit tests."""
import json
import urllib.error
import urllib.request
from flask import current_app

class MPError(Exception):
    pass

def api(method, path, payload=None, *, idempotency_key=None):
    token = current_app.config.get('MP_ACCESS_TOKEN')
    if not token:
        raise MPError('mercadopago_not_configured')
    if not path.startswith('/') or '://' in path:
        raise MPError('invalid_api_path')
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if idempotency_key:
        headers['X-Idempotency-Key'] = idempotency_key
    req = urllib.request.Request('https://api.mercadopago.com' + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.loads(response.read(1024 * 1024))
    except (urllib.error.URLError, ValueError) as exc:
        raise MPError('mercadopago_request_failed') from exc
