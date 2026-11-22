
"""COM-02.1.11.2: pruebas aisladas del endpoint PDF."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask, g

from app.api.contract_signature_admin import bp


URL = (
    "/api/v1/contracts/1/"
    "signature-management/documents/1/pdf"
)


@pytest.fixture
def environment(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        CONTRACT_DOCUMENT_STORAGE_ROOT=str(tmp_path),
    )

    app.register_blueprint(bp, url_prefix="/api/v1")

    endpoint = "contract_signature_admin.download_document"
    view = app.view_functions[endpoint]

    # Aislar exclusivamente el controlador.
    while hasattr(view, "__wrapped__"):
        view = view.__wrapped__

    def isolated_view(contract_id, document_id):
        g.tenant_id = 1
        return view(contract_id, document_id)

    app.view_functions[endpoint] = isolated_view

    with app.test_client() as client:
        yield client, tmp_path


def make_document(storage: Path):
    content = b"%PDF-1.4\nPDF de prueba\n%%EOF"
    key = "tenants/1/contracts/1/test.pdf"

    path = storage / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    document = SimpleNamespace(
        id=1,
        tenant_id=1,
        contract_id=1,
        version=1,
        storage_key=key,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
    )

    return document, path, content


def test_descarga_pdf_autorizada(environment):
    client, storage = environment
    document, _, content = make_document(storage)

    with patch(
        "app.api.contract_signature_admin.db.session.scalar",
        return_value=document,
    ):
        response = client.get(URL)

    assert response.status_code == 200
    assert response.data == content
    assert response.mimetype == "application/pdf"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_documento_de_otro_tenant_retorna_404(environment):
    client, _ = environment

    # Simula una consulta filtrada por tenant sin resultados.
    with patch(
        "app.api.contract_signature_admin.db.session.scalar",
        return_value=None,
    ):
        response = client.get(URL)

    assert response.status_code == 404
    assert response.get_json()["error"] == "document_not_found"



def test_integridad_invalida_retorna_409(environment):
    client, storage = environment
    document, path, _ = make_document(storage)

    # Alterar únicamente el archivo temporal de prueba.
    path.write_bytes(path.read_bytes() + b"ALTERADO")

    with patch(
        "app.api.contract_signature_admin.db.session.scalar",
        return_value=document,
    ):
        response = client.get(URL)

    assert response.status_code == 409

    data = response.get_json()
    assert data is not None
    assert data["error"] == "document_integrity_failed"

