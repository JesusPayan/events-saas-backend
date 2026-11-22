
import hashlib
import json
from dataclasses import dataclass

from flask import request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.extensions import db
from app.models.api_idempotency_key import ApiIdempotencyKey


@dataclass
class IdempotencyResult:
    record: ApiIdempotencyKey | None = None
    replay_status: int | None = None
    replay_body: dict | None = None
    error: str | None = None


def request_fingerprint(operation, resource, payload):
    canonical = json.dumps(
        {
            "operation": operation,
            "resource": resource,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def acquire_idempotency(
    tenant_id,
    operation,
    resource,
    payload,
):
    key = request.headers.get("Idempotency-Key")

    if key is None:
        return IdempotencyResult()

    if (
        not key
        or len(key) > 128
        or any(ord(char) < 33 or ord(char) > 126 for char in key)
    ):
        return IdempotencyResult(
            error="invalid_idempotency_key"
        )

    fingerprint = request_fingerprint(
        operation,
        resource,
        payload,
    )

    # SAVEPOINT: un conflicto UNIQUE no debe
    # invalidar la transacción externa.
    record = ApiIdempotencyKey(
        tenant_id=tenant_id,
        operation=operation,
        idempotency_key=key,
        request_hash=fingerprint,
    )

    try:
        with db.session.begin_nested():
            db.session.add(record)
            db.session.flush()

        return IdempotencyResult(record=record)

    except IntegrityError:
        # El SAVEPOINT revierte únicamente el INSERT.
        # Recuperar la solicitud ya confirmada mediante
        # una lectura actual.
        existing = db.session.scalar(
            select(ApiIdempotencyKey)
            .where(
                ApiIdempotencyKey.tenant_id == tenant_id,
                ApiIdempotencyKey.operation == operation,
                ApiIdempotencyKey.idempotency_key == key,
            )
            .with_for_update()
        )

        if existing is None:
            return IdempotencyResult(
                error="idempotency_retry_required"
            )

        if existing.request_hash != fingerprint:
            return IdempotencyResult(
                error="idempotency_key_conflict"
            )

        if existing.response_status is None:
            return IdempotencyResult(
                error="idempotency_retry_required"
            )

        return IdempotencyResult(
            replay_status=existing.response_status,
            replay_body=existing.response_body,
        )

    except OperationalError:
        # Evitar confirmar una operación cuando la
        # coordinación de idempotencia no fue posible.
        db.session.rollback()
        return IdempotencyResult(
            error="idempotency_retry_required"
        )


def complete_idempotency(record, status, body):
    if record is None:
        return

    record.response_status = status
    record.response_body = body
