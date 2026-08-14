# AGENTS.md

This repository contains only the standalone Dobrokek web quiz and the tools required to build and operate it. The Telegram content-sharing bot and the legacy episode `video_builder` live in a different repository and must not be added here.

## Components

- `pack_builder/` — local Python 3.12/Telethon CLI that reads the Telegram channel, transcodes selected videos with FFmpeg, and produces a validated ZIP pack.
- `backend/` — FastAPI, WebSocket game server, SQLAlchemy/Alembic, and SQLite persistence.
- `frontend/` — React/TypeScript/Vite client for hosts and players.
- `shared/` — pack and WebSocket event JSON schemas shared across components.
- `deploy/` — Caddy configuration for SPA, API, WebSocket, and direct media delivery.
- `scripts/` — SQLite backup and statistics export helpers.

The production server never connects to Telegram. Telegram credentials and session files are used only by `pack_builder/` on the owner's computer.

## Commands

From the repository root:

```bash
make install       # Create .venv and install backend, Pack Builder, and frontend dependencies
make test          # Ruff, Python tests, frontend tests, and production frontend build
make dev           # Build and run quiz-api + quiz-web with Docker Compose
make backend-dev   # Run API and local media server for Vite development
make frontend-dev  # Run Vite on port 5173 with hot reload
make build         # Build production Docker images
make pack-install  # Install only the local Pack Builder into pack_builder/.venv
make export        # Export meme statistics from a running server
```

Production:

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f quiz-api
docker compose down
```

Backend development:

```bash
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Frontend development:

```bash
# Terminal 1: FastAPI + media for the Vite proxy
make backend-dev

# Terminal 2: Vite with hot reload
make frontend-dev
```

Pack Builder:

```bash
cd pack_builder
.venv/bin/dobrokek-pack scan --channel -1001234567890 --authors ./authors.yaml
.venv/bin/dobrokek-pack build \
  --channel -1001234567890 \
  --authors ./authors.yaml \
  --count 20 \
  --title "Доброкек — пак №1" \
  --output ./result/dobrokek-pack-01.zip
```

## Runtime architecture

```text
Local Telegram channel access
  -> pack_builder
  -> ZIP (manifest.json + videos/*.mp4)
  -> host upload
  -> FastAPI validation/import
  -> SQLite metadata + /data/quiz/media
  -> Caddy serves media and React
  -> WebSocket synchronizes one room with up to five players
```

The API must use exactly one Uvicorn worker because the active WebSocket connection manager is in process memory. Caddy, not FastAPI, serves video files and HTTP Range requests.

## Data and security rules

- Never commit `.env`, Telegram `.session` files, `authors.yaml`, SQLite files, generated packs, or `quiz-data/`.
- Keep `HOST_SECRET` and `ADMIN_TOKEN` at least 16 bytes long and distinct.
- Do not expose a full manifest, Telegram IDs, or the correct author before reveal.
- Keep shared pack validation aligned with `shared/pack-schema.json`.
- Persist only the active pack's media; retain archived metadata, answers, reactions, and Telegram source IDs.
- Use Alembic for schema changes. Do not create production tables ad hoc at application startup.
- Run the relevant tests after changes and preserve the Windows/WSL/Linux Pack Builder workflow.
