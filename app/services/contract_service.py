"""COM-02.1: contratos generados desde cotizaciones aceptadas."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.contract import Contract
from app.models.contract_item import ContractItem
from app.models.contract_status_history import ContractStatusHistory
from app.models.quote import Quote
from app.models.quote_item import QuoteItem
from app.models.quote_status_history import QuoteStatusHistory


CONTRACT_TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class ContractError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def decimal_value(value):
    return Decimal("0.00") if value is None else Decimal(str(value))


def generate_contract_number():
    return f"CON-{uuid4().hex[:20].upper()}"


def get_contract(tenant_id, contract_id):
    return db.session.scalar(
        select(Contract).where(
            Contract.tenant_id == tenant_id,
            Contract.id == contract_id,
        )
    )


def get_contract_by_quote(tenant_id, quote_id):
    return db.session.scalar(
        select(Contract).where(
            Contract.tenant_id == tenant_id,
            Contract.quote_id == quote_id,
        )
    )


def list_contracts(tenant_id, page=1, per_page=20):
    page = max(1, int(page))
    per_page = min(100, max(1, int(per_page)))
    stmt = (
        select(Contract)
        .where(Contract.tenant_id == tenant_id)
        .order_by(Contract.created_at.desc(), Contract.id.desc())
    )
    return db.paginate(stmt, page=page, per_page=per_page, error_out=False)


def create_contract_from_quote(tenant_id, quote_id, user_id):
    """Crea contrato y convierte cotización de forma atómica.

    Esta función controla commit/rollback. No realizar commit en la API.
    """
    try:
        quote = db.session.scalar(
            select(Quote)
            .where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
            .with_for_update()
        )
        if quote is None:
            raise ContractError("quote_not_found", "La cotización no existe.", 404)

        # Priorizar el conflicto por duplicidad, incluso si ya está convertida.
        if get_contract_by_quote(tenant_id, quote_id) is not None:
            raise ContractError(
                "contract_already_exists", "La cotización ya tiene un contrato.", 409
            )

        if quote.status != "accepted":
            raise ContractError(
                "quote_not_accepted", "Solo se pueden contratar cotizaciones aceptadas.", 409
            )

        quote_items = db.session.scalars(
            select(QuoteItem)
            .where(QuoteItem.tenant_id == tenant_id, QuoteItem.quote_id == quote.id)
            .order_by(QuoteItem.sort_order.asc(), QuoteItem.id.asc())
        ).all()
        if not quote_items:
            raise ContractError(
                "quote_without_items", "La cotización no contiene conceptos.", 409
            )
        if decimal_value(quote.total) <= 0:
            raise ContractError(
                "invalid_quote_total", "La cotización debe tener un importe positivo.", 409
            )

        now = utc_now()
        contract = Contract(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_id=quote.event_id,
            client_id=quote.client_id,
            contract_number=generate_contract_number(),
            status="draft",
            currency=quote.currency,
            subtotal=decimal_value(quote.subtotal),
            discount_total=decimal_value(quote.discount_total),
            tax_total=decimal_value(quote.tax_total),
            total=decimal_value(quote.total),
            notes=quote.notes,
            terms_conditions=quote.terms_conditions,
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        db.session.add(contract)
        db.session.flush()

        for item in quote_items:
            db.session.add(
                ContractItem(
                    tenant_id=tenant_id,
                    contract_id=contract.id,
                    description=item.description,
                    item_type=item.item_type,
                    quantity=decimal_value(item.quantity),
                    unit_price=decimal_value(item.unit_price),
                    discount_amount=decimal_value(item.discount_amount),
                    tax_rate=decimal_value(item.tax_rate),
                    tax_amount=decimal_value(item.tax_amount),
                    subtotal=decimal_value(item.subtotal),
                    total=decimal_value(item.total),
                    sort_order=item.sort_order,
                )
            )

        db.session.add(
            ContractStatusHistory(
                tenant_id=tenant_id,
                contract_id=contract.id,
                previous_status=None,
                new_status="draft",
                notes="Contrato generado desde cotización aceptada.",
                changed_by=user_id,
                created_at=now,
            )
        )

        quote.status = "converted"
        quote.updated_at = now
        db.session.add(
            QuoteStatusHistory(
                tenant_id=tenant_id,
                quote_id=quote.id,
                previous_status="accepted",
                new_status="converted",
                changed_by=user_id,
                notes=f"Convertida en contrato {contract.contract_number}",
            )
        )
        db.session.commit()
        return contract

    except ContractError:
        db.session.rollback()
        raise
    except IntegrityError as exc:
        db.session.rollback()
        raise ContractError(
            "contract_conflict", "No se pudo crear el contrato por un conflicto de datos.", 409
        ) from exc
    except Exception:
        db.session.rollback()
        raise


def change_contract_status(tenant_id, contract_id, new_status, user_id, notes=None):
    try:
        contract = db.session.scalar(
            select(Contract)
            .where(Contract.tenant_id == tenant_id, Contract.id == contract_id)
            .with_for_update()
        )
        if contract is None:
            raise ContractError("contract_not_found", "El contrato no existe.", 404)

        allowed = CONTRACT_TRANSITIONS.get(contract.status, set())
        if new_status not in allowed:
            raise ContractError(
                "invalid_status_transition",
                f"No se permite cambiar de {contract.status} a {new_status}.",
                409,
            )

        previous_status = contract.status
        contract.status = new_status
        contract.updated_at = utc_now()
        db.session.add(
            ContractStatusHistory(
                tenant_id=tenant_id,
                contract_id=contract.id,
                previous_status=previous_status,
                new_status=new_status,
                notes=notes,
                changed_by=user_id,
                created_at=utc_now(),
            )
        )
        db.session.commit()
        return contract
    except ContractError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise


def get_contract_history(tenant_id, contract_id):
    if get_contract(tenant_id, contract_id) is None:
        raise ContractError("contract_not_found", "El contrato no existe.", 404)
    return db.session.scalars(
        select(ContractStatusHistory)
        .where(
            ContractStatusHistory.tenant_id == tenant_id,
            ContractStatusHistory.contract_id == contract_id,
        )
        .order_by(
            ContractStatusHistory.created_at.asc(),
            ContractStatusHistory.id.asc(),
        )
    ).all()


def serialize_contract(contract, include_items=False):
    data = {
        "id": contract.id,
        "tenant_id": contract.tenant_id,
        "quote_id": contract.quote_id,
        "event_id": contract.event_id,
        "client_id": contract.client_id,
        "contract_number": contract.contract_number,
        "status": contract.status,
        "currency": contract.currency,
        "subtotal": str(contract.subtotal),
        "discount_total": str(contract.discount_total),
        "tax_total": str(contract.tax_total),
        "total": str(contract.total),
        "notes": contract.notes,
        "terms_conditions": contract.terms_conditions,
        "created_by": contract.created_by,
        "created_at": contract.created_at.isoformat() if contract.created_at else None,
        "updated_at": contract.updated_at.isoformat() if contract.updated_at else None,
    }
    if include_items:
        items = db.session.scalars(
            select(ContractItem)
            .where(
                ContractItem.tenant_id == contract.tenant_id,
                ContractItem.contract_id == contract.id,
            )
            .order_by(ContractItem.sort_order.asc(), ContractItem.id.asc())
        ).all()
        data["items"] = [
            {
                "id": item.id,
                "description": item.description,
                "item_type": item.item_type,
                "quantity": str(item.quantity),
                "unit_price": str(item.unit_price),
                "discount_amount": str(item.discount_amount),
                "tax_rate": str(item.tax_rate),
                "tax_amount": str(item.tax_amount),
                "subtotal": str(item.subtotal),
                "total": str(item.total),
            }
            for item in items
        ]
    return data


def serialize_contract_history(history):
    return {
        "id": history.id,
        "contract_id": history.contract_id,
        "previous_status": history.previous_status,
        "new_status": history.new_status,
        "notes": history.notes,
        "changed_by": history.changed_by,
        "created_at": history.created_at.isoformat() if history.created_at else None,
    }
