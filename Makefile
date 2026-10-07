.PHONY: install compose-up migrate run-api run-web run-simulator run-worker lint test

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
	@echo "Database migrations are not set up yet."

run-api:
	.venv/bin/cloudsentry-api

run-web:
	npm --prefix web run dev

run-simulator:
	.venv/bin/cloudsentry-simulator

run-worker:
	.venv/bin/cloudsentry-worker

lint:
	$(BIN)ruff check api worker simulator
	$(BIN)ruff format --check api worker simulator

test:
	$(BIN)pytest
