# Frame Chain Studio

Frame Chain Studio is a first-stage mock implementation for long-form AI storyboard video generation. It models a workflow of keyframe review, video generation, tail-frame extraction, and start-frame inheritance across ordered shots.

This stage intentionally does not integrate paid AI APIs, large models, or authentication.

## Stack

- Frontend: Vue 3, Vite, TypeScript, Element Plus, Pinia, Vue Router, Vitest.
- Backend: Python 3.11, FastAPI, SQLModel, SQLite, pytest.
- Media: FFmpeg and FFprobe.
- Runtime: Docker Compose.

## Layout

- `backend/app`: FastAPI application, domain services, SQLModel entities, providers, media helpers.
- `backend/tests`: backend unit and integration tests.
- `frontend/src`: Vue app, routes, Pinia store, API client, views, tests.
- `scripts`: start and test helpers.

## Backend Workflow

Shot states are validated on the backend:

`DRAFT -> KEYFRAME_GENERATING -> KEYFRAME_REVIEW -> KEYFRAME_APPROVED -> VIDEO_GENERATING -> VIDEO_REVIEW -> VIDEO_APPROVED -> TAIL_FRAME_LOCKED -> COMPLETED`

Rejection paths:

- keyframe review can return to `DRAFT`.
- video review can return to `KEYFRAME_APPROVED`.
- generation failure returns to the last editable approved state.

All generation requests, assets, task logs, state changes, and errors are persisted in SQLite.

## Local Development

Backend:

```bash
cd backend
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Docker:

```bash
docker compose up --build
```

Open the app at `http://localhost:5173`. The API is available at `http://localhost:8000/api`.

## Tests

Backend:

```bash
cd backend
pytest
ruff check .
mypy app tests
```

Frontend:

```bash
cd frontend
npm run test
npm run typecheck
npm run build
```

All checks:

```bash
./scripts/test.sh
```

On Windows PowerShell:

```powershell
.\scripts\test.ps1
```

## Database Initialization

The backend uses an explicit startup initializer, `SQLModel.metadata.create_all`, in `app.db.init_db()`. This keeps the first stage simple while making schema creation deterministic. A migration tool can be added when schema evolution begins.
