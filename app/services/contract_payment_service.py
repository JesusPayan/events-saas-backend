
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, func

from app.extensions import db
from app.models.contract import Contract
from app.models.contract_payment import ContractPayment
from app.models.contract_payment_audit import ContractPaymentAudit


CENT = Decimal("0.01")


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PaymentError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def parse_amount(value):
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise PaymentError(
            "invalid_amount",
            "El importe debe ser un número decimal positivo.",
        )

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PaymentError(
            "invalid_amount",
            "Importe inválido.",
        )

    if (
        not amount.is_finite()
        or amount <= 0
        or amount.as_tuple().exponent < -2
        or amount > Decimal("999999999999.99")
    ):
        raise PaymentError(
            "invalid_amount",
            "El importe debe ser positivo y tener máximo dos decimales.",
        )

    return amount.quantize(CENT)


def get_locked_contract(tenant_id, contract_id):
    contract = db.session.scalar(
        select(Contract)
        .where(
            Contract.tenant_id == tenant_id,
            Contract.id == contract_id,
        )
        .with_for_update()
    )

    if contract is None:
        raise PaymentError(
            "contract_not_found",
            "Contrato no encontrado.",
            404,
        )

    return contract


def confirmed_total(tenant_id, contract_id):
    value = db.session.scalar(
        select(func.coalesce(func.sum(ContractPayment.amount), 0))
        .where(
            ContractPayment.tenant_id == tenant_id,
            ContractPayment.contract_id == contract_id,
            ContractPayment.status == "confirmed",
        )
    )

    return Decimal(str(value)).quantize(CENT)


def get_balance(tenant_id, contract_id):
    contract = db.session.scalar(
        select(Contract).where(
            Contract.tenant_id == tenant_id,
            Contract.id == contract_id,
        )
    )

    if contract is None:
        raise PaymentError(
            "contract_not_found",
            "Contrato no encontrado.",
            404,
        )

    paid = confirmed_total(tenant_id, contract_id)
    total = Decimal(str(contract.total)).quantize(CENT)

    return {
        "contract_id": contract.id,
        "currency": contract.currency,
        "total": str(total),
        "paid": str(paid),
        "balance": str(total - paid),
    }


def register_payment(
    tenant_id,
    contract_id,
    user_id,
    amount,
    payment_type,
    payment_method,
    reference=None,
    notes=None,
):
    amount = parse_amount(amount)

    if (
        not isinstance(payment_type, str)
        or payment_type not in ("advance", "installment")
    ):
        raise PaymentError(
        "invalid_payment_type",
        "Tipo de pago inválido.",
    )

    if (
        not isinstance(payment_method, str)
        or payment_method not in (
            "cash",
            "bank_transfer",
            "card",
            "other",
        )
    ):
        raise PaymentError(
        "invalid_payment_method",
        "Método de pago inválido.",
    )

    if reference is not None and (
        not isinstance(reference, str)
        or not reference.strip()
        or len(reference) > 120
    ):
        raise PaymentError("invalid_reference", "Referencia inválida.")

    if notes is not None and (
        not isinstance(notes, str) or len(notes) > 2000
    ):
        raise PaymentError("invalid_notes", "Notas inválidas.")

    reference = reference.strip() if reference else None

    try:
        contract = get_locked_contract(tenant_id, contract_id)

        if contract.status != "active":
            raise PaymentError(
                "contract_not_active",
                "Solo se permiten pagos para contratos activos.",
                409,
            )

        if reference:
            existing = db.session.scalar(
                select(ContractPayment.id).where(
                    ContractPayment.tenant_id == tenant_id,
                    ContractPayment.contract_id == contract_id,
                    ContractPayment.reference == reference,
                )
            )
            if existing is not None:
                raise PaymentError(
                    "duplicate_reference",
                    "La referencia ya está registrada.",
                    409,
                )

        payment = ContractPayment(
            tenant_id=tenant_id,
            contract_id=contract_id,
            payment_type=payment_type,
            amount=amount,
            currency=contract.currency,
            payment_method=payment_method,
            reference=reference,
            status="pending",
            notes=notes,
            created_by=user_id,
        )

        db.session.add(payment)
        db.session.flush()

        db.session.add(
            ContractPaymentAudit(
                tenant_id=tenant_id,
                payment_id=payment.id,
                action="created",
                previous_status=None,
                new_status="pending",
                changed_by=user_id,
            )
        )

        db.session.commit()
        return payment

    except Exception:
        db.session.rollback()
        raise


def confirm_payment(tenant_id, contract_id, payment_id, user_id):
    try:
        # Todas las confirmaciones de un contrato se serializan
        # mediante el bloqueo de su fila.
        contract = get_locked_contract(tenant_id, contract_id)

        if contract.status != "active":
            raise PaymentError(
                "contract_not_active",
                "El contrato no está activo.",
                409,
            )

        payment = db.session.scalar(
            select(ContractPayment)
            .where(
                ContractPayment.id == payment_id,
                ContractPayment.tenant_id == tenant_id,
                ContractPayment.contract_id == contract_id,
            )
            .with_for_update()
        )

        if payment is None:
            raise PaymentError("payment_not_found", "Pago no encontrado.", 404)

        if payment.status != "pending":
            raise PaymentError(
                "invalid_payment_status",
                "Solo pueden confirmarse pagos pendientes.",
                409,
            )

        paid = confirmed_total(tenant_id, contract_id)
        total = Decimal(str(contract.total))

        if paid + payment.amount > total:
            raise PaymentError(
                "payment_exceeds_balance",
                "El pago excede el saldo pendiente.",
                409,
            )

        payment.status = "confirmed"
        payment.confirmed_at = utc_now()
        payment.confirmed_by = user_id

        db.session.add(
            ContractPaymentAudit(
                tenant_id=tenant_id,
                payment_id=payment.id,
                action="confirmed",
                previous_status="pending",
                new_status="confirmed",
                changed_by=user_id,
            )
        )

        db.session.commit()
        return payment

    except Exception:
        db.session.rollback()
        raise

def serialize_payment(payment):
    return {
        "id": payment.id,
        "tenant_id": payment.tenant_id,
        "contract_id": payment.contract_id,
        "payment_type": payment.payment_type,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "payment_method": payment.payment_method,
        "reference": payment.reference,
        "status": payment.status,
        "notes": payment.notes,
        "paid_at": (
            payment.paid_at.isoformat()
            if payment.paid_at else None
        ),
        "confirmed_at": (
            payment.confirmed_at.isoformat()
            if payment.confirmed_at else None
        ),
        "created_by": payment.created_by,
        "confirmed_by": payment.confirmed_by,
        "created_at": (
            payment.created_at.isoformat()
            if payment.created_at else None
        ),
        "updated_at": (
            payment.updated_at.isoformat()
            if payment.updated_at else None
        ),
    }


def serialize_payment_audit(audit):
    return {
        "id": audit.id,
        "payment_id": audit.payment_id,
        "action": audit.action,
        "previous_status": audit.previous_status,
        "new_status": audit.new_status,
        "notes": audit.notes,
        "changed_by": audit.changed_by,
        "created_at": (
            audit.created_at.isoformat()
            if audit.created_at else None
        ),
    }


def list_payments(tenant_id, contract_id):
    contract = db.session.scalar(
        select(Contract.id).where(
            Contract.tenant_id == tenant_id,
            Contract.id == contract_id,
        )
    )

    if contract is None:
        raise PaymentError(
            "contract_not_found",
            "Contrato no encontrado.",
            404,
        )

    return db.session.scalars(
        select(ContractPayment)
        .where(
            ContractPayment.tenant_id == tenant_id,
            ContractPayment.contract_id == contract_id,
        )
        .order_by(
            ContractPayment.created_at.desc(),
            ContractPayment.id.desc(),
        )
    ).all()


def list_payment_audits(tenant_id, contract_id, payment_id):
    payment = db.session.scalar(
        select(ContractPayment.id).where(
            ContractPayment.tenant_id == tenant_id,
            ContractPayment.contract_id == contract_id,
            ContractPayment.id == payment_id,
        )
    )

    if payment is None:
        raise PaymentError(
            "payment_not_found",
            "Pago no encontrado.",
            404,
        )

    return db.session.scalars(
        select(ContractPaymentAudit)
        .where(
            ContractPaymentAudit.tenant_id == tenant_id,
            ContractPaymentAudit.payment_id == payment_id,
        )
        .order_by(
            ContractPaymentAudit.created_at.asc(),
            ContractPaymentAudit.id.asc(),
        )
    ).all()


def cancel_payment(
    tenant_id,
    contract_id,
    payment_id,
    user_id,
    notes=None,
):
    if notes is not None and (
        not isinstance(notes, str)
        or len(notes) > 2000
    ):
        raise PaymentError(
            "invalid_notes",
            "Notas inválidas.",
        )

    try:
        # Bloquear el contrato antes del pago:
        # mismo orden de bloqueo que confirm_payment.
        get_locked_contract(tenant_id, contract_id)

        payment = db.session.scalar(
            select(ContractPayment)
            .where(
                ContractPayment.tenant_id == tenant_id,
                ContractPayment.contract_id == contract_id,
                ContractPayment.id == payment_id,
            )
            .with_for_update()
        )

        if payment is None:
            raise PaymentError(
                "payment_not_found",
                "Pago no encontrado.",
                404,
            )

        if payment.status != "pending":
            raise PaymentError(
                "invalid_payment_status",
                "Solo pueden cancelarse pagos pendientes.",
                409,
            )

        payment.status = "cancelled"

        db.session.add(
            ContractPaymentAudit(
                tenant_id=tenant_id,
                payment_id=payment.id,
                action="cancelled",
                previous_status="pending",
                new_status="cancelled",
                notes=notes.strip() if notes else None,
                changed_by=user_id,
            )
        )

        db.session.commit()
        return payment

    except Exception:
        db.session.rollback()
        raise
