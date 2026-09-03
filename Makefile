.PHONY: install dev backend-dev backend-dev-stop frontend-dev test build \
	pack-setup pack-install pack-check pack-scan pack-build pack-help export

DEV_COMPOSE = docker compose -f docker-compose.yaml -f docker-compose.dev.yaml
PACK_DIR = pack_builder
PACK_POETRY = cd $(PACK_DIR) && POETRY_VIRTUALENVS_IN_PROJECT=true poetry
PACK_AUTHORS ?= ./authors.yaml
PACK_CHANNEL ?=
PACK_FROM_DATE ?=
PACK_TO_DATE ?=
PACK_COUNT ?= 50
PACK_TITLE ?= Доброкек — пак №1
PACK_OUTPUT ?= ./result/dobrokek-pack.zip
PACK_SEED ?=
PACK_SELECTION ?= random
PACK_MAX_DURATION ?= 30
PACK_MAX_FILE_SIZE ?= 50
PACK_SKIP_UNKNOWN ?= 1
PACK_BUILD_FLAGS ?=

PACK_COMMON_ARGS = --authors "$(PACK_AUTHORS)" \
	$(if $(strip $(PACK_CHANNEL)),--channel "$(PACK_CHANNEL)") \
	$(if $(strip $(PACK_FROM_DATE)),--from-date "$(PACK_FROM_DATE)") \
	$(if $(strip $(PACK_TO_DATE)),--to-date "$(PACK_TO_DATE)")

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -e 'backend[dev]' -e 'pack_builder[dev]'
	cd frontend && npm install

pack-install:
	$(PACK_POETRY) install --extras dev

pack-setup: pack-install
	@test -f $(PACK_DIR)/.env || cp $(PACK_DIR)/.env.example $(PACK_DIR)/.env
	@test -f $(PACK_DIR)/authors.yaml || cp $(PACK_DIR)/authors.example.yaml $(PACK_DIR)/authors.yaml
	@echo "Pack Builder настроен. Заполните $(PACK_DIR)/.env и $(PACK_DIR)/authors.yaml."

pack-check:
	@test -f $(PACK_DIR)/.env || (echo "Нет $(PACK_DIR)/.env. Выполните: make pack-setup"; exit 1)
	@test -f $(PACK_DIR)/authors.yaml || (echo "Нет $(PACK_DIR)/authors.yaml. Выполните: make pack-setup"; exit 1)
	@test -x $(PACK_DIR)/.venv/bin/dobrokek-pack || (echo "Pack Builder не установлен. Выполните: make pack-install"; exit 1)
	@command -v ffmpeg >/dev/null || (echo "FFmpeg не найден в PATH"; exit 1)
	@command -v ffprobe >/dev/null || (echo "FFprobe не найден в PATH"; exit 1)

pack-scan: pack-check
	$(PACK_POETRY) run dobrokek-pack scan $(PACK_COMMON_ARGS)

pack-build: pack-check
	$(PACK_POETRY) run dobrokek-pack build $(PACK_COMMON_ARGS) \
		--count "$(PACK_COUNT)" \
		--title "$(PACK_TITLE)" \
		--selection "$(PACK_SELECTION)" \
		--output "$(PACK_OUTPUT)" $(if $(strip $(PACK_SEED)),--seed "$(PACK_SEED)") \
		$(if $(filter 1 true yes,$(PACK_SKIP_UNKNOWN)),--skip-unknown-authors) $(PACK_BUILD_FLAGS) \
		--max-duration "$(PACK_MAX_DURATION)" \
		--max-file-size "$(PACK_MAX_FILE_SIZE)"

pack-help:
	@echo 'Первичная настройка: make pack-setup'
	@echo 'Проверка канала:    make pack-scan'
	@echo 'Сборка пака:        make pack-build PACK_TITLE="Доброкек — пак №1"'
	@echo 'Параметры: PACK_CHANNEL, PACK_FROM_DATE, PACK_TO_DATE, PACK_COUNT,'
	@echo '           PACK_TITLE, PACK_OUTPUT, PACK_SEED, PACK_SELECTION, PACK_MAX_DURATION,'
	@echo '           PACK_MAX_FILE_SIZE, PACK_SKIP_UNKNOWN, PACK_BUILD_FLAGS'

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
