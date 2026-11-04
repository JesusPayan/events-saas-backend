
from datetime import datetime, timezone

from sqlalchemy import select
from app.extensions import db

from app.models.inventory_incident_charge import (
    InventoryIncidentCharge
)
from app.models.inventory_charge_audit import (
    InventoryChargeAudit
)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ChargeError(Exception):
    def __init__(self, code, status=409):
        self.code = code
        self.status = status
        super().__init__(code)


TRANSITIONS = {
    "pending": {
        "approve": "approved",
        "waive": "waived"
    },
    "approved": {
        "pay": "paid",
        "waive": "waived"
    }
}


def change_charge_status(
    tenant_id,
    charge_id,
    user_id,
    action,
    data
):
    if not isinstance(data, dict):
        raise ChargeError("invalid_json", 400)

    notes = data.get("notes")

    if notes is not None:
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ChargeError("invalid_notes", 400)
        notes = notes.strip() or None

    try:
        charge = db.session.scalar(
            select(InventoryIncidentCharge)
            .where(
                InventoryIncidentCharge.id == charge_id,
                InventoryIncidentCharge.tenant_id == tenant_id
            )
            .with_for_update()
        )

        if charge is None:
            raise ChargeError("charge_not_found", 404)

        previous_status = charge.status

        next_status = TRANSITIONS.get(
            previous_status, {}
        ).get(action)

        if next_status is None:
            raise ChargeError(
                "invalid_charge_transition"
            )

        now = utc_now()

        if action == "approve":
            if charge.amount <= 0:
                raise ChargeError(
                    "charge_amount_must_be_positive"
                )

            charge.approved_by = user_id
            charge.approved_at = now

        elif action == "waive":
            if not notes:
                raise ChargeError(
                    "waiver_reason_required", 400
                )

            charge.waived_by = user_id
            charge.waived_at = now
            charge.resolution_notes = notes

        elif action == "pay":
            reference = data.get("payment_reference")
            method = data.get("payment_method")

            if (
                not isinstance(reference, str)
                or not reference.strip()
                or len(reference) > 120
            ):
                raise ChargeError(
                    "invalid_payment_reference", 400
                )

            if method not in (
                "cash",
                "transfer",
                "card",
                "other"
            ):
                raise ChargeError(
                    "invalid_payment_method", 400
                )

            charge.paid_at = now
            charge.payment_reference = reference.strip()
            charge.payment_method = method

        charge.status = next_status

        audit = InventoryChargeAudit(
            tenant_id=tenant_id,
            charge_id=charge.id,
            previous_status=previous_status,
            new_status=next_status,
            notes=notes,
            changed_by=user_id
        )

        db.session.add(audit)
        db.session.flush()

        result = charge.to_dict()

        db.session.commit()
        return result

    except Exception:
        db.session.rollback()
        raise
