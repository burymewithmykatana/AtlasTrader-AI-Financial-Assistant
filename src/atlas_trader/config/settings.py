"""Environment-backed application settings with safe trading defaults."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlas_trader import __version__
from atlas_trader.domain.enums.execution_mode import ExecutionMode


class Settings(BaseSettings):
    """Application settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AtlasTrader"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_version: str = __version__
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    trading_mode: ExecutionMode = ExecutionMode.PAPER
    live_trading_enabled: bool = False

    postgres_db: str = "atlas_trader"
    postgres_user: str = "atlas"
    postgres_password: SecretStr = SecretStr("change-me")
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    database_url: SecretStr | None = None

    nobitex_env: Literal["testnet", "production"] = "testnet"
    nobitex_testnet_base_url: str = ""
    nobitex_production_base_url: str = "https://api.nobitex.ir"
    nobitex_token: SecretStr | None = None
    nobitex_public_base_url: str = "https://api.nobitex.ir"
    nobitex_public_timeout_seconds: Decimal = Field(default=Decimal("15"), gt=0, le=120)
    nobitex_public_max_attempts: int = Field(default=3, ge=1, le=6)
    nobitex_public_backoff_seconds: Decimal = Field(default=Decimal("0.5"), ge=0, le=30)
    nobitex_user_agent: str = "AtlasTrader/0.1.0"
    asset_classifications: dict[str, str] = Field(
        default_factory=lambda: {
            "IRT": "fiat",
            "RLS": "fiat",
            "USDT": "stablecoin",
            "USDC": "stablecoin",
            "DAI": "stablecoin",
            "XAUT": "gold_backed",
            "PAXG": "gold_backed",
        }
    )

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: SecretStr | None = None

    max_position_pct: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)
    max_daily_loss_pct: Decimal = Field(default=Decimal("0.01"), ge=0, le=1)
    max_open_positions: int = Field(default=3, ge=1)
    max_spread_bps: int = Field(default=40, ge=0)
    cooldown_minutes: int = Field(default=60, ge=0)
    stale_data_seconds: int = Field(default=90, ge=1)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def require_async_postgres_driver(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")
        return value

    @model_validator(mode="after")
    def enforce_live_trading_interlock(self) -> Self:
        """Production orders require two independent, explicit settings."""
        if self.trading_mode is ExecutionMode.LIVE and not self.live_trading_enabled:
            raise ValueError(
                "TRADING_MODE=live requires LIVE_TRADING_ENABLED=true; "
                "live trading remains disabled"
            )
        if self.live_trading_enabled and self.trading_mode is not ExecutionMode.LIVE:
            raise ValueError("LIVE_TRADING_ENABLED=true is only valid with TRADING_MODE=live")
        if (
            self.app_env == "production"
            and self.database_url is None
            and self.postgres_password.get_secret_value() == "change-me"
        ):
            raise ValueError(
                "production requires a non-default PostgreSQL password or DATABASE_URL"
            )
        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"postgresql+asyncpg://{user}:{password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
