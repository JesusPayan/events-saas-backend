from flask import Blueprint, jsonify
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
