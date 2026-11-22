from flask import Blueprint, jsonify
from sqlalchemy import text
from app.extensions import db
import os

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "eventos-api"}), 200


@bp.get("/ready")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ready", "database": "ok"}), 200
    except Exception:
        db.session.rollback()
        return jsonify({"status": "unavailable"}), 503

@bp.get("/e2e/readiness")
def e2e_readiness():
    environment = os.getenv("FLASK_ENV", "").lower()

    if environment != "test":
        return jsonify({
            "status": "unavailable"
        }), 404

    database = db.session.execute(
        text("SELECT DATABASE()")
    ).scalar()

    if database != "crm_events_test":
        return jsonify({
            "status": "unsafe_environment"
        }), 503

    return jsonify({
        "status": "ready",
        "environment": "test",
        "database": database
    }), 200