.PHONY: lint test

lint:
	ruff check api worker simulator
	ruff format --check api worker simulator

test:
	pytest
