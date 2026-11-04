from datetime import datetime, timezone
from app.extensions import db


class Tenant(db.Model):
    __tablename__ = "tenants"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    status = db.Column(db.String(30), nullable=False, default="active")
    timezone = db.Column(db.String(64), nullable=False, default="America/Mazatlan")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
