import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_phase2_has_no_private_nobitex_execution_path() -> None:
    client = (
        (ROOT / "src/atlas_trader/infrastructure/exchanges/nobitex/client.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    adapter = (
        (ROOT / "src/atlas_trader/infrastructure/exchanges/nobitex/adapter.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    phase2 = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (ROOT / "src/atlas_trader/application").glob("*.py")
    )

    for forbidden in (
        "/market/orders/add",
        "/market/orders/update-status",
        "withdraw",
        "pro=yes",
        "authorization",
        "nobitex_token",
    ):
        assert forbidden not in client
        assert forbidden not in phase2
    assert "no authenticated" in adapter


def test_no_secret_environment_file_is_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert [path for path in tracked if Path(path).name.startswith(".env")] == [".env.example"]
