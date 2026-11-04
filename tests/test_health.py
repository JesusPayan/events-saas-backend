import pytest
from app import create_app


@pytest.fixture()
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    return app.test_client()


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "service": "eventos-api"}


def test_unknown_endpoint(client):
    assert client.get("/api/v1/unknown").status_code == 404
