from uuid import UUID

from fastapi.testclient import TestClient

from atlas_trader.main import create_app


def test_health_endpoint_is_structured_and_safe() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={"X-Correlation-ID": "test-cycle"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "AtlasTrader",
        "version": "0.1.0",
        "environment": "test",
        "trading_mode": "paper",
        "live_trading_enabled": False,
    }
    assert response.headers["X-Correlation-ID"] == "test-cycle"


def test_invalid_correlation_id_is_replaced() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={"X-Correlation-ID": "invalid id with spaces"})

    assert response.status_code == 200
    UUID(response.headers["X-Correlation-ID"])


def test_unhandled_error_has_safe_structured_boundary() -> None:
    application = create_app()

    @application.get("/_test/error")
    async def raise_unhandled_error() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(application) as client:
        response = client.get("/_test/error", headers={"X-Correlation-ID": "error-cycle"})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "internal_server_error",
        "correlation_id": "error-cycle",
    }
    assert response.headers["X-Correlation-ID"] == "error-cycle"
