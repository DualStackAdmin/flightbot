.PHONY: install up down logs migrate revision test lint fmt loadtest stats

install:
	pip install -e ".[dev]"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100 bot worker

migrate:
	alembic upgrade head

revision:
	@test -n "$(m)" || (echo 'usage: make revision m="description"'; exit 1)
	alembic revision --autogenerate -m "$(m)"

test:
	pytest -q

lint:
	ruff check . && ruff format --check .

fmt:
	ruff format . && ruff check . --fix

loadtest:
	python -m scripts.loadtest --yes

stats:
	python -m flightbot.cli stats
