"""Endpoints públicos (sin autenticación) para el sitio comercial."""
from flask import Blueprint, jsonify

from app.extensions import limiter
from app.services.billing.catalog_service import public_catalog

bp = Blueprint("public", __name__)


@bp.get("/public/plans")
@limiter.limit("60 per minute")
def plans():
    """Planes y precios vigentes (MXN) para la landing. Sin datos de empresas ni usuarios."""
    response = jsonify(public_catalog())
    # Cache corto en el navegador/proxy: los precios cambian solo desde el panel global.
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
