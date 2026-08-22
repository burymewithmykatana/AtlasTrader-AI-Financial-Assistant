import json
from pathlib import Path
from typing import Any

WORKFLOW_ROOT = Path(__file__).parents[2] / "n8n" / "workflows"
EXPECTED = {
    "01_market_data_sync": "/market-data/sync",
    "02_paper_trading_cycle": "/trading/cycle",
    "03_paper_reconciliation": "/trading/reconcile",
    "04_watchdog": "/admin/status",
    "05_daily_report": "/portfolio",
}


def load_workflow(name: str) -> dict[str, Any]:
    value = json.loads((WORKFLOW_ROOT / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_sanitized_thin_phase2_workflows_match_api_contracts() -> None:
    for name, required_route in EXPECTED.items():
        workflow = load_workflow(name)
        serialized = json.dumps(workflow)
        node_types = {node["type"] for node in workflow["nodes"]}

        assert workflow["name"] == name
        assert workflow["active"] is False
        assert required_route in serialized
        assert node_types <= {
            "n8n-nodes-base.scheduleTrigger",
            "n8n-nodes-base.httpRequest",
            "n8n-nodes-base.if",
            "n8n-nodes-base.noOp",
        }
        assert "credentials" not in serialized.lower()
        assert "authorization" not in serialized.lower()
        assert "nobitex_token" not in serialized.lower()
        assert "/market/orders" not in serialized.lower()


def test_paper_cycle_delegates_position_size_and_watchdog_never_resets_safety_state() -> None:
    cycle = json.dumps(load_workflow("02_paper_trading_cycle"))
    watchdog = json.dumps(load_workflow("04_watchdog"))

    assert "signal_id" in cycle
    assert "quantity" not in cycle
    assert "/admin/resume" not in watchdog
    assert "/admin/reset-kill" not in watchdog
    assert "/trading/cycle" not in watchdog
