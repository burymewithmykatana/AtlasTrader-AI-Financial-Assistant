import pytest
from pydantic import ValidationError

from atlas_trader.config.settings import Settings
from atlas_trader.domain.enums.execution_mode import ExecutionMode


def test_safe_defaults_use_paper_mode() -> None:
    settings = Settings(_env_file=None)

    assert settings.trading_mode is ExecutionMode.PAPER
    assert settings.live_trading_enabled is False
    assert settings.nobitex_public_base_url == "https://api.nobitex.ir"


def test_live_mode_requires_second_explicit_interlock() -> None:
    with pytest.raises(ValidationError, match="LIVE_TRADING_ENABLED=true"):
        Settings(trading_mode=ExecutionMode.LIVE, live_trading_enabled=False, _env_file=None)


def test_live_flag_cannot_be_armed_in_a_non_live_mode() -> None:
    with pytest.raises(ValidationError, match="only valid with TRADING_MODE=live"):
        Settings(trading_mode=ExecutionMode.TESTNET, live_trading_enabled=True, _env_file=None)


def test_database_url_escapes_credentials() -> None:
    settings = Settings(postgres_user="user@local", postgres_password="p/a:ss", _env_file=None)

    assert "user%40local:p%2Fa%3Ass" in settings.sqlalchemy_database_url


def test_secret_values_are_redacted_from_repr() -> None:
    settings = Settings(nobitex_token="top-secret", _env_file=None)

    assert "top-secret" not in repr(settings)


def test_database_url_requires_asyncpg() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(database_url="postgresql://atlas:secret@localhost/atlas", _env_file=None)


def test_log_level_is_normalized_and_validated() -> None:
    settings = Settings(log_level="warning", _env_file=None)
    assert settings.log_level == "WARNING"

    with pytest.raises(ValidationError):
        Settings(log_level="verbose", _env_file=None)


def test_production_rejects_default_database_password() -> None:
    with pytest.raises(ValidationError, match="non-default PostgreSQL password"):
        Settings(app_env="production", postgres_password="change-me", _env_file=None)
