.PHONY: up down restart logs clean seed lint test base

base:
	docker build -t quorum-base -f Dockerfile.base .

up: base
	docker compose up -d --build

down:
	docker compose down

restart: base
	docker compose down && docker compose up -d --build

logs:
	docker compose logs -f api worker frontend

clean:
	docker compose down -v

seed:
	docker compose exec api python scripts/seed_labeled_qa.py --file db/seed/labeled_qa.json

lint:
	uv run ruff check api backend worker

test:
	uv run pytest tests -v
