from flask import Blueprint, jsonify, current_app
from sqlalchemy import text
from app.extensions import db

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
    if current_app.config.get("APP_ENV") != "test":
        return jsonify(error="not_found"), 404
    try:
        database = db.session.execute(text("SELECT DATABASE()")).scalar()
        if database != "crm_events_test":
            return jsonify(status="unavailable"), 503
        return jsonify(status="ready", environment="test", database=database), 200
    except Exception:
        db.session.rollback()
        return jsonify(status="unavailable"), 503
