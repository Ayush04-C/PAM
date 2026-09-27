"""Tests for the HTTP foundation."""

from fastapi.testclient import TestClient

from pam.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_generated_and_returned() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_request_id_is_preserved_when_supplied() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"X-Request-ID": "test-request-id"})

    assert response.headers["X-Request-ID"] == "test-request-id"
