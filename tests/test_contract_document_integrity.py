"""COM-02.1.11: pruebas aisladas, sin MySQL ni archivos de producción."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.services.contract_document_service import (
    ContractDocumentError,
    read_verified_document,
)


@pytest.fixture
def storage(tmp_path):
    app = Flask(__name__)
    app.config['CONTRACT_DOCUMENT_STORAGE_ROOT'] = str(tmp_path)
    with app.app_context():
        yield tmp_path


def make_document(storage: Path, data=b'%PDF-1.4\nprueba controlada\n%%EOF'):
    relative = 'tenants/999/contracts/999/test.pdf'
    path = storage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return SimpleNamespace(
        storage_key=relative,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    ), path


def assert_error(document, expected):
    with pytest.raises(ContractDocumentError) as exc:
        read_verified_document(document)
    assert exc.value.code == expected
    assert exc.value.status_code == 409


def test_documento_original_integro(storage):
    document, _ = make_document(storage)
    assert read_verified_document(document).startswith(b'%PDF-')


def test_sha256_incorrecto(storage):
    document, _ = make_document(storage)
    document.sha256 = '0' * 64
    assert_error(document, 'document_integrity_failed')


def test_tamano_incorrecto(storage):
    document, _ = make_document(storage)
    document.byte_size += 1
    assert_error(document, 'document_integrity_failed')


def test_archivo_fisicamente_alterado(storage):
    document, path = make_document(storage)
    path.write_bytes(path.read_bytes() + b'alterado')
    assert_error(document, 'document_integrity_failed')


def test_archivo_no_pdf(storage):
    document, _ = make_document(storage, b'contenido que no es PDF')
    assert_error(document, 'document_integrity_failed')


def test_archivo_inexistente(storage):
    document, path = make_document(storage)
    path.unlink()
    assert_error(document, 'document_file_missing')


def test_ruta_fuera_del_directorio(storage):
    document, _ = make_document(storage)
    document.storage_key = '../fuera.pdf'
    assert_error(document, 'invalid_storage_key')


def test_ruta_absoluta_fuera_del_directorio(storage):
    document, _ = make_document(storage)
    document.storage_key = str(storage.parent / 'fuera.pdf')
    assert_error(document, 'invalid_storage_key')


def test_symlink_rechazado(storage):
    document, path = make_document(storage)
    link = path.with_name('link.pdf')
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip('El sistema no permite crear enlaces simbólicos')
    document.storage_key = 'tenants/999/contracts/999/link.pdf'
    assert_error(document, 'document_file_missing')
