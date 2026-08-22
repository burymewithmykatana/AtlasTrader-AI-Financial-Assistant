from fastapi.testclient import TestClient

from atlas_trader.main import create_app


def test_phase1_api_routes_are_declared_without_trading_routes() -> None:
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()

    paths = document["paths"]
    assert "get" in paths["/markets"]
    assert "post" in paths["/market-data/sync"]
    assert "get" in paths["/market-data/candles"]
    assert {"get", "post"} <= set(paths["/backtests"])
    assert "get" in paths["/backtests/{run_id}"]
    assert all(
        forbidden not in path
        for path in paths
        for forbidden in ("order", "wallet", "balance", "withdraw", "telegram")
    )
