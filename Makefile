.PHONY: install dev api web test lint demo backfill up down

install:
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm install

api:        ## API + embedded scheduler on :8000 (SQLite)
	cd backend && EMBEDDED_WORKER=true uvicorn app.main:app --reload --port 8000

web:        ## dashboard on :5173
	cd frontend && npm run dev

demo:       ## synthetic data so the dashboard works offline
	cd backend && python -m scripts.seed_demo

backfill:   ## 30 days of real GDELT news + prices for backtesting
	cd backend && python -m scripts.backfill --days 30

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check . && ruff format --check .

up:         ## full stack: Postgres, Redis, API, worker, dashboard
	docker compose up --build

down:
	docker compose down
