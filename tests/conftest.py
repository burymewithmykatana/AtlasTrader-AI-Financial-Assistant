from collections.abc import Iterator

import pytest

from atlas_trader.config.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
