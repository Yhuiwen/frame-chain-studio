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
- `backend/tests/fixtures`: committed Mock Provider and integration-test media fixtures.
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

## Shot Deletion Strategy

Shot deletion is supported in the first stage. The backend deletes database records for the selected Shot inside one rollback-safe operation:

- Shot state changes, task logs, generation requests, and asset records owned by the deleted Shot are removed.
- Physical media files are not deleted, because a file path can be shared by derived assets.
- Asset records are deleted only when they are not referenced by records outside the deletion set.
- If a middle Shot is deleted, the next Shot's automatic start-frame inheritance is rebuilt from the previous Shot's locked tail frame when one exists.
- If no previous locked tail frame exists, the next Shot's automatic start frame is cleared.
- Remaining Shot `sort_order` values are reindexed to be continuous and stable.

Manual start-frame assignment is not implemented in this stage. Existing automatic start-frame records can be rebuilt or cleared by deletion; there is no manual upload/assignment API yet.

## Asset Summary Structure

Project detail responses include structured per-Shot asset summaries so the frontend does not infer inheritance from logs:

```json
{
  "start_frame": {
    "asset_id": 12,
    "url": "/api/media/12",
    "source_type": "inherited",
    "source_shot_id": 1,
    "source_shot_title": "Shot 1",
    "file_name": "tail-frame-shot-1.png",
    "created_at": "2026-07-18T00:00:00Z"
  },
  "target_keyframe": {
    "asset_id": 10,
    "url": "/api/media/10",
    "source_type": "generated"
  },
  "locked_tail_frame": {
    "asset_id": 11,
    "url": "/api/media/11",
    "source_type": "generated"
  }
}
```

The media endpoint only serves database-registered files under the configured storage directory and returns the stored content type. Full local disk paths are not exposed to the frontend.

## Runtime Files

- Test fixtures live in `backend/tests/fixtures/` and are committed to Git.
- The default SQLite database is `backend/data/frame_chain.db`.
- The default generated media storage is `backend/data/storage/`.
- Runtime databases, generated media, logs, caches, and temporary files are ignored by Git.
- The first stage does not support manual start-frame upload or manual start-frame assignment.
- The first stage only includes the local Mock Provider and does not integrate a real asynchronous AI generation platform.

## Frontend Refresh And Polling

The project detail page uses a single local refresh function to reload project metadata, shots, structured assets, requests, and logs without a full-page reload. Generation actions refresh once immediately, then start finite polling when active tasks exist. Polling uses one timeout chain, avoids overlapping requests, stops on terminal task states, stops on unmount, slows down while the tab is hidden, and refreshes immediately when the tab becomes visible again.

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

Docker Desktop must be running before container startup or container-level verification. You can still validate the Compose file with:

```powershell
docker compose config
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

```powershell
.\scripts\check.ps1
```

```bash
./scripts/test.sh
```

On Windows PowerShell:

```powershell
.\scripts\test.ps1
```

## Database Initialization

The backend uses an explicit startup initializer, `SQLModel.metadata.create_all`, in `app.db.init_db()`. This keeps the first stage simple while making schema creation deterministic. A migration tool can be added when schema evolution begins.
