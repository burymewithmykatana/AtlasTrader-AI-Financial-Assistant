from fastapi.testclient import TestClient

from atlas_trader.main import create_app


def test_public_and_paper_api_routes_are_declared_without_private_exchange_routes() -> None:
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()

    paths = document["paths"]
    assert "get" in paths["/markets"]
    assert "post" in paths["/market-data/sync"]
    assert "get" in paths["/market-data/candles"]
    assert {"get", "post"} <= set(paths["/backtests"])
    assert "get" in paths["/backtests/{run_id}"]
    assert "post" in paths["/trading/cycle"]
    assert "post" in paths["/trading/reconcile"]
    assert "get" in paths["/orders"]
    assert "get" in paths["/portfolio"]
    assert "get" in paths["/signals"]
    assert all(
        forbidden not in path
        for path in paths
        for forbidden in ("wallet", "withdraw", "telegram", "testnet", "live")
    )
