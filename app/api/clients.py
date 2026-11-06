
from flask import Blueprint, request, jsonify, g
from sqlalchemy import select, or_, func
from app.extensions import db
from app.models.crm import Client
from app.schemas.clients import validate_client
from app.security import tenant_permission
#hola
bp = Blueprint("clients", __name__)


def find_client(client_id):
    return db.session.scalar(
        select(Client).where(
            Client.id == client_id,
            Client.tenant_id == g.tenant_id
        )
    )


@bp.get("/clients")
@tenant_permission("clients.read")
def list_clients():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(
            100, max(1, int(request.args.get("per_page", 20)))
        )
    except ValueError:
        return jsonify(error="invalid_pagination"), 400

    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    if status and status not in ("active", "inactive"):
        return jsonify(error="invalid_status"), 400

    stmt = select(Client).where(
        Client.tenant_id == g.tenant_id
    )

    if status:
        stmt = stmt.where(Client.status == status)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(or_(
            Client.first_name.ilike(pattern),
            Client.last_name.ilike(pattern),
            Client.business_name.ilike(pattern),
            Client.email.ilike(pattern),
            Client.phone.ilike(pattern)
        ))

    total = db.session.scalar(
        select(func.count()).select_from(stmt.subquery())
    )

    clients = db.session.scalars(
        stmt.order_by(Client.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    return jsonify(
        items=[client.to_dict() for client in clients],
        total=total,
        page=page,
        per_page=per_page
    ), 200


@bp.post("/clients")
@tenant_permission("clients.create")
def create_client():
    data, errors = validate_client(
        request.get_json(silent=True)
    )

    if errors:
        return jsonify(error="validation_error", details=errors), 400

    client = Client(
        tenant_id=g.tenant_id,
        **data
    )

    try:
        db.session.add(client)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify(client.to_dict()), 201


@bp.get("/clients/<int:client_id>")
@tenant_permission("clients.read")
def get_client(client_id):
    client = find_client(client_id)

    if client is None:
        return jsonify(error="client_not_found"), 404

    return jsonify(client.to_dict()), 200


@bp.patch("/clients/<int:client_id>")
@tenant_permission("clients.update")
def update_client(client_id):
    client = find_client(client_id)

    if client is None:
        return jsonify(error="client_not_found"), 404

    data, errors = validate_client(
        request.get_json(silent=True),
        partial=True
    )

    if errors:
        return jsonify(error="validation_error", details=errors), 400

    for key, value in data.items():
        setattr(client, key, value)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify(client.to_dict()), 200


@bp.patch("/clients/<int:client_id>/deactivate")
@tenant_permission("clients.update")
def deactivate_client(client_id):
    client = find_client(client_id)

    if client is None:
        return jsonify(error="client_not_found"), 404

    client.status = "inactive"

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return jsonify(client.to_dict()), 200
