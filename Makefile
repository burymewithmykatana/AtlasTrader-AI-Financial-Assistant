.PHONY: install test lint typecheck format run up down migrate markets-sync candles-sync backtest

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy

format:
	python -m ruff format .
	python -m ruff check --fix .

run:
	uvicorn atlas_trader.main:app --reload

up:
	docker compose up --build

down:
	docker compose down

migrate:
	alembic upgrade head

markets-sync:
	python -m atlas_trader.cli markets-sync

candles-sync:
	python -m atlas_trader.cli candles-sync --symbol "$(SYMBOL)" --timeframe "$(TIMEFRAME)" --start "$(START)" --end "$(END)"

backtest:
	python -m atlas_trader.cli backtest --symbol "$(SYMBOL)" --timeframe "$(TIMEFRAME)" --start "$(START)" --end "$(END)"
