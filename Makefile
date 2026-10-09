.PHONY: install compose-up migrate migrate-down run-api run-web run-simulator run-worker seed-simulator simulator-metrics simulator-billing simulator-tags simulator-deps lint test

BIN := $(if $(wildcard .venv/bin/ruff),.venv/bin/,)

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt
	.venv/bin/pip install -e ./api -e ./worker -e ./simulator
	npm --prefix web ci

compose-up:
	test -f .env || cp .env.example .env
	docker compose up -d

migrate:
	.venv/bin/alembic -c api/alembic.ini upgrade head

migrate-down:
	.venv/bin/alembic -c api/alembic.ini downgrade base

run-api:
	.venv/bin/cloudsentry-api

run-web:
	npm --prefix web run dev

run-simulator:
	.venv/bin/cloudsentry-simulator

seed-simulator:
	.venv/bin/python -m simulator.seed

simulator-metrics:
	.venv/bin/python -m simulator.metrics

simulator-billing:
	.venv/bin/python -m simulator.billing

simulator-tags:
	.venv/bin/python -m simulator.tags

simulator-deps:
	.venv/bin/python -m simulator.dependencies

run-worker:
	.venv/bin/cloudsentry-worker

lint:
	$(BIN)ruff check api worker simulator
	$(BIN)ruff format --check api worker simulator

test:
	$(BIN)pytest
