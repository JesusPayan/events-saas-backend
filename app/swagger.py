
from pathlib import Path

from flask import send_file
from flask_swagger_ui import get_swaggerui_blueprint


def init_swagger(app):
    """Registra la especificación OpenAPI y Swagger UI."""

    openapi_path = (
        Path(app.root_path).parent / "openapi.json"
    )

    @app.get("/api/openapi.json")
    def openapi_spec():
        if not openapi_path.is_file():
            return {
                "error": "openapi_file_not_found"
            }, 404

        return send_file(
            openapi_path,
            mimetype="application/json"
        )

    swagger_blueprint = get_swaggerui_blueprint(
        "/api/docs",
        "/api/openapi.json",
        config={
            "app_name": "Eventos SaaS API",
            "docExpansion": "list",
            "deepLinking": True
        }
    )

    app.register_blueprint(
        swagger_blueprint,
        url_prefix="/api/docs"
    )

