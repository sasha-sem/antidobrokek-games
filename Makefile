.PHONY: install dev backend-dev backend-dev-stop frontend-dev test build pack-install export

DEV_COMPOSE = docker compose -f docker-compose.yaml -f docker-compose.dev.yaml

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -e 'backend[dev]' -e 'pack_builder[dev]'
	cd frontend && npm install

pack-install:
	python3.12 -m venv pack_builder/.venv
	pack_builder/.venv/bin/pip install -e 'pack_builder[dev]'

dev:
	docker compose up --build quiz-api quiz-web

backend-dev:
	$(DEV_COMPOSE) up --build quiz-api quiz-media

backend-dev-stop:
	$(DEV_COMPOSE) stop quiz-api quiz-media

frontend-dev:
	cd frontend && npm run dev

test:
	.venv/bin/ruff check backend pack_builder
	PYTHONPATH=pack_builder .venv/bin/pytest pack_builder/tests
	cd backend && PYTHONPATH=. ../.venv/bin/pytest tests
	cd frontend && npm test && npm run build

build:
	docker compose build quiz-api quiz-web

export:
	./scripts/export_quiz_stats.sh
