import json
from collections.abc import Callable
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest

from atlas_trader.domain.enums.asset_class import AssetClass
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.infrastructure.exchanges.nobitex.dto import (
    OptionsResponseDTO,
    OrderBookDTO,
    OrderBooksResponseDTO,
    TradesResponseDTO,
    UdfHistoryDTO,
)
from atlas_trader.infrastructure.exchanges.nobitex.errors import NobitexResponseError
from atlas_trader.infrastructure.exchanges.nobitex.mapper import (
    map_market,
    map_orderbook,
    map_public_trade,
    map_udf_history,
    timeframe_to_udf,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "nobitex"


def load(name: str) -> dict[str, object]:
    result = json.loads((FIXTURES / name).read_text(encoding="utf-8"), parse_float=Decimal)
    assert isinstance(result, dict)
    return result


def test_options_dto_and_market_mapping_preserve_decimal() -> None:
    options = OptionsResponseDTO.from_payload(load("options.json"))
    market = map_market(
        "BTCUSDT",
        options,
        classifications={"USDT": AssetClass.STABLECOIN},
    )

    assert market.amount_step == Decimal("0.000001")
    assert market.price_step == Decimal("0.01")
    assert market.min_order_amount == Decimal("10")
    assert market.amount_precision == 6
    assert market.quote_asset_class is AssetClass.STABLECOIN
    assert all(
        isinstance(value, Decimal)
        for value in (market.amount_step, market.price_step, market.min_order_amount)
    )


def test_asset_classification_is_configurable_and_unknown_assets_work() -> None:
    options = OptionsResponseDTO.from_payload(load("options.json"))

    gold = map_market("XAUTUSDT", options, classifications={"XAUT": AssetClass.GOLD_BACKED})
    unknown = map_market("ABCUSDT", options, classifications={})

    assert gold.base_asset_class is AssetClass.GOLD_BACKED
    assert unknown.base_asset_class is AssetClass.UNKNOWN


def test_orderbook_mapping_uses_v3_bid_ask_orientation() -> None:
    dto = OrderBookDTO.model_validate(load("orderbook_symbol.json"))
    book = map_orderbook("BTCUSDT", dto)

    assert book.bids[0].price == Decimal("65000.11")
    assert book.asks[0].price == Decimal("65000.13")
    assert book.timestamp.tzinfo is UTC


def test_all_orderbooks_dynamic_keys_validate() -> None:
    dto = OrderBooksResponseDTO.from_payload(load("orderbooks_all.json"))

    assert set(dto.books) == {"BTCUSDT", "XAUTUSDT", "ABCUSDT"}


def test_failed_or_empty_discovery_responses_are_rejected() -> None:
    with pytest.raises(NobitexResponseError, match="failed status"):
        OptionsResponseDTO.from_payload({"status": "failed", "nobitex": {}})
    with pytest.raises(NobitexResponseError, match="no markets"):
        OrderBooksResponseDTO.from_payload({"status": "ok"})


def test_udf_mapping_and_invalid_ohlc_rejection() -> None:
    valid, rejected = map_udf_history(
        "BTCUSDT", Timeframe.FIFTEEN_MINUTES, UdfHistoryDTO.from_payload(load("udf_history.json"))
    )
    invalid, invalid_rejected = map_udf_history(
        "BTCUSDT",
        Timeframe.FIFTEEN_MINUTES,
        UdfHistoryDTO.from_payload(load("udf_invalid_ohlc.json")),
    )

    assert [candle.open for candle in valid] == [
        Decimal("65000.00"),
        Decimal("65010.00"),
        Decimal("65005.00"),
    ]
    assert rejected == 0
    assert invalid == ()
    assert invalid_rejected == 1


def test_recent_public_trade_mapping() -> None:
    response = TradesResponseDTO.from_payload(load("trades.json"))
    trade = map_public_trade("BTCUSDT", response.trades[0])

    assert trade.price == Decimal("65000.12")
    assert trade.amount == Decimal("0.002")
    assert trade.timestamp.tzinfo is UTC


@pytest.mark.parametrize(
    ("fixture_name", "parser"),
    [
        ("orderbook_malformed_numeric.json", OrderBookDTO.from_payload),
        ("orderbook_malformed_level.json", OrderBookDTO.from_payload),
        ("trades_malformed_numeric.json", TradesResponseDTO.from_payload),
        ("udf_malformed_numeric.json", UdfHistoryDTO.from_payload),
    ],
)
def test_malformed_vendor_numerics_surface_stable_response_errors(
    fixture_name: str,
    parser: Callable[[dict[str, object]], object],
) -> None:
    with pytest.raises(NobitexResponseError, match="invalid"):
        parser(load(fixture_name))


@pytest.mark.parametrize(
    ("timeframe", "resolution"),
    [
        (Timeframe.ONE_MINUTE, "1"),
        (Timeframe.FIVE_MINUTES, "5"),
        (Timeframe.FIFTEEN_MINUTES, "15"),
        (Timeframe.THIRTY_MINUTES, "30"),
        (Timeframe.ONE_HOUR, "60"),
        (Timeframe.FOUR_HOURS, "240"),
        (Timeframe.ONE_DAY, "D"),
    ],
)
def test_timeframe_mapping(timeframe: Timeframe, resolution: str) -> None:
    assert timeframe_to_udf(timeframe) == resolution
