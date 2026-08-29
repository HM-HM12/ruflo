.PHONY: install install-dev test lint format migrate backtest paper-trade api docker-up docker-down

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

test:
	pytest -v --cov=src --cov-report=term-missing

lint:
	ruff check src tests scripts
	mypy src --ignore-missing-imports

format:
	ruff format src tests scripts

migrate:
	alembic upgrade head

backtest:
	python -m scripts.run_backtest --symbol AAPL --days 180

paper-trade:
	python -m scripts.run_paper_trading

api:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

docker-up:
	docker compose up --build

docker-down:
	docker compose down
