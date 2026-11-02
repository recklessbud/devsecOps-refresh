from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_item_found():
    assert client.get("/items/1").json() == {"id": 1, "name": "alpha"}


def test_item_not_found():
    assert client.get("/items/999").status_code == 404


def test_item_validation_rejects_bad_input():
    assert client.get("/items/abc").status_code == 422
    assert client.get("/items/-5").status_code == 422


def test_security_headers_present():
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
