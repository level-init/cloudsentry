.PHONY: install compose-up migrate migrate-down run-api run-web run-simulator run-worker ingest-inventory ingest-metrics ingest-billing ingest-knowledge seed-simulator simulator-metrics simulator-billing simulator-tags simulator-deps simulator-incidents simulator-scenarios lint test

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

simulator-incidents:
	.venv/bin/python -m simulator.incidents

simulator-scenarios:
	.venv/bin/python -m simulator.scenarios

run-worker:
	.venv/bin/cloudsentry-worker

ingest-inventory:
	.venv/bin/python -m worker.main ingest-inventory

ingest-metrics:
	.venv/bin/python -m worker.main ingest-metrics

ingest-billing:
	.venv/bin/python -m worker.main ingest-billing

ingest-knowledge:
	.venv/bin/python -m worker.main ingest-knowledge

lint:
	$(BIN)ruff check api worker simulator
	$(BIN)ruff format --check api worker simulator

test:
	$(BIN)pytest
