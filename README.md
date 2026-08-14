# Доброкек — веб-викторина

Самостоятельный проект совместной викторины по мем-видео. Игроки одновременно смотрят ролик, угадывают его автора, затем ставят лайк или дизлайк. Ответы, реакции и Telegram ID исходных сообщений сохраняются в SQLite.

Telegram-бот для приёма контента и старый сборщик выпусков находятся в отдельном репозитории `dobrokek-bot` и не являются частью или зависимостью этого проекта.

## Состав проекта

- `pack_builder/` — локальная CLI-утилита на Telethon для чтения канала и сборки ZIP-пака;
- `backend/` — FastAPI, WebSocket, SQLAlchemy, Alembic и SQLite;
- `frontend/` — React, TypeScript и Vite;
- `shared/` — JSON Schema формата пака и WebSocket-событий;
- `deploy/` — production-конфигурация Caddy;
- `scripts/` — backup SQLite и экспорт статистики.

Pack Builder работает на компьютере владельца: входит в Telegram через пользовательскую сессию, выбирает видео, кодирует их в H.264/AAC и создаёт ZIP. Telegram-сессия никогда не отправляется на сервер.

Создатель комнаты загружает ZIP через сайт, вводит имя и участвует наравне с остальными. Отдельной роли ведущего в игровом процессе нет: когда все подключённые игроки готовы, сервер автоматически запускает preload, вопрос, раскрытие ответа и следующий раунд. Ссылка вида `/room/KEK4PX` сама показывает форму имени и ведёт в лобби.

Backend проверяет JSON Schema, безопасные пути, SHA-256 и кодеки, сохраняет метаданные и атомарно активирует пак. Caddy напрямую отдаёт MP4 с поддержкой HTTP Range. При активации нового пака старые видео удаляются, но статистика, ответы, реакции и Telegram ID остаются.

## Быстрый запуск сайта

```bash
cp .env.example .env
# Задайте разные HOST_SECRET и ADMIN_TOKEN длиной не менее 16 байт.
# DOMAIN=:80 оставляет локальный HTTP, DOMAIN=quiz.example.com включает автоматический HTTPS.

docker compose build
docker compose up -d
docker compose ps
docker compose logs -f quiz-api
```

После запуска сайт доступен по адресу из `DOMAIN`. Остановка:

```bash
docker compose down
```

База и активные медиа сохраняются в `./quiz-data`. API запускается с одним Uvicorn worker, поскольку менеджер активных WebSocket-соединений хранится в памяти процесса.

## Pack Builder: Linux и WSL

Нужны Python 3.12 и FFmpeg/FFprobe в `PATH`. Для Ubuntu/WSL:

```bash
sudo apt install ffmpeg python3.12-venv
make pack-install
cp pack_builder/.env.example pack_builder/.env
cp pack_builder/authors.example.yaml pack_builder/authors.yaml
cd pack_builder
```

Заполните `.env`, затем просканируйте канал:

```bash
.venv/bin/dobrokek-pack scan \
  --channel -1001234567890 \
  --authors ./authors.yaml
```

Создание первого пака:

```bash
.venv/bin/dobrokek-pack build \
  --channel -1001234567890 \
  --authors ./authors.yaml \
  --count 20 \
  --title "Доброкек — пак №1" \
  --seed 2026-08-14 \
  --output ./result/dobrokek-pack-01.zip
```

Первый запуск попросит номер телефона, Telegram-код и, при необходимости, пароль 2FA. Последующие запуски используют локальную `.session`.

## Pack Builder: Windows PowerShell

Установите Python 3.12 и FFmpeg, например `winget install Gyan.FFmpeg`, затем из корня репозитория:

```powershell
py -3.12 -m venv pack_builder\.venv
pack_builder\.venv\Scripts\pip.exe install -e "pack_builder[dev]"
Copy-Item pack_builder\.env.example pack_builder\.env
Copy-Item pack_builder\authors.example.yaml pack_builder\authors.yaml
Set-Location pack_builder

.\.venv\Scripts\dobrokek-pack.exe scan `
  --channel -1001234567890 `
  --authors .\authors.yaml

.\.venv\Scripts\dobrokek-pack.exe build `
  --channel -1001234567890 `
  --authors .\authors.yaml `
  --count 20 `
  --title "Доброкек — пак №1" `
  --output .\result\dobrokek-pack-01.zip
```

`.env`, `authors.yaml`, Telegram-сессия, `history.sqlite3` и готовые паки игнорируются Git. Нераспознанный автор по умолчанию останавливает сборку; пропустить такие сообщения можно явным флагом `--skip-unknown-authors`.

## Локальная разработка

### Frontend с автоматическим обновлением

Для разработки React не нужно пересобирать Docker-контейнер после каждого изменения. Нужны Docker Compose и Node.js 22.22+ (либо 24.15+).

Первичная настройка из корня репозитория:

```bash
cp .env.example .env
# Замените HOST_SECRET и ADMIN_TOKEN в .env.
cd frontend
npm install
cd ..
```

Затем откройте два терминала. В первом одной командой запустите FastAPI, миграции и раздачу видео:

```bash
make backend-dev
```

Во втором запустите Vite:

```bash
make frontend-dev
```

Откройте [http://localhost:5173](http://localhost:5173). При сохранении файлов в `frontend/src` страница обновляется автоматически. Vite проксирует API и WebSocket на `127.0.0.1:8000`, а видео — на `127.0.0.1:8080`.

Остановка backend, если он был оставлен в фоне:

```bash
make backend-dev-stop
```

Подробная инструкция по структуре frontend и проверкам находится в [`frontend/README.md`](frontend/README.md).

Установка всех Python- и frontend-зависимостей, полная проверка и production-сборка:

```bash
make install
make test
make build
```

Команда `make dev` оставлена для production-подобного запуска собранных `quiz-api` и `quiz-web`; hot reload работает через `make backend-dev` + `make frontend-dev`.

## Статистика и резервные копии

CSV из работающего приложения:

```bash
ADMIN_TOKEN='your-admin-token' \
QUIZ_URL='https://quiz.example.com' \
./scripts/export_quiz_stats.sh
```

То же через Make:

```bash
ADMIN_TOKEN='your-admin-token' QUIZ_URL='http://localhost' make export
```

Резервная копия SQLite:

```bash
DATA_DIR=./quiz-data ./scripts/backup_quiz_db.sh
```

Backup использует SQLite backup API, проверяет целостность и оставляет последние семь копий. Видео в backup не входят.

JSON-экспорт:

```bash
curl -H 'X-Admin-Token: your-admin-token' \
  'https://quiz.example.com/api/admin/meme-stats.json?min_votes=2&sort=rating&order=desc'
```

## Ограничения MVP

- Одновременно открыта только одна комната, в ней может быть до пяти игроков.
- Физически хранятся только видео активного пака.
- Перекодирование выполняется локально; VPS только валидирует готовые MP4.
- Очистка `localStorage` или вход через другой браузер создаёт новую игровую идентичность.
- После перезапуска API клиенты переподключаются и получают snapshot; менеджер соединений поэтому работает с одним worker.
