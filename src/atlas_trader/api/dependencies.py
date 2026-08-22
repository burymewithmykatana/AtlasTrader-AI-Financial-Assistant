from atlas_trader.config.settings import Settings
from atlas_trader.domain.enums.asset_class import AssetClass
from atlas_trader.infrastructure.exchanges.nobitex.adapter import NobitexPublicAdapter
from atlas_trader.infrastructure.exchanges.nobitex.client import NobitexPublicClient, RetryPolicy


def create_nobitex_public_client(settings: Settings) -> NobitexPublicClient:
    return NobitexPublicClient(
        base_url=settings.nobitex_public_base_url,
        timeout_seconds=float(settings.nobitex_public_timeout_seconds),
        user_agent=settings.nobitex_user_agent,
        retry_policy=RetryPolicy(
            max_attempts=settings.nobitex_public_max_attempts,
            base_delay_seconds=float(settings.nobitex_public_backoff_seconds),
        ),
    )


def create_nobitex_public_adapter(
    client: NobitexPublicClient, settings: Settings
) -> NobitexPublicAdapter:
    classifications = {
        asset.upper(): AssetClass(classification)
        for asset, classification in settings.asset_classifications.items()
    }
    return NobitexPublicAdapter(client, asset_classifications=classifications)
