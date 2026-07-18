# AGENTS.md

## Directory Responsibilities

- `backend/app/api`: FastAPI routes and API response boundaries.
- `backend/app/core`: configuration, shared errors, and app-level plumbing.
- `backend/app/domain`: pure domain rules such as the Shot state machine.
- `backend/app/models`: SQLModel entities and Pydantic schemas.
- `backend/app/providers`: `GenerationProvider` implementations. Domain services must depend on the abstraction, not on a concrete provider.
- `backend/app/services`: application workflows, persistence, state validation, and orchestration.
- `backend/app/media`: FFmpeg and FFprobe helpers.
- `backend/tests`: pytest unit and integration tests.
- `backend/tests/fixtures`: committed media fixtures used by tests and the Mock Provider.
- `frontend/src/api`: typed API client.
- `frontend/src/stores`: Pinia stores.
- `frontend/src/views`: routed Vue views.
- `frontend/src/components`: reusable Vue components.
- `scripts`: local start and verification helpers.

## Code Standards

- Keep backend state transitions in services/domain code. Do not rely on frontend-only validation.
- Persist generation requests, assets, logs, state changes, and errors for every generation workflow.
- Keep provider implementations replaceable through `GenerationProvider`.
- Do not integrate paid AI APIs, large model downloads, or user login in the first stage.
- Prefer focused tests around state transitions and media workflow behavior.
- Keep Vue views practical and workflow-first.
- Do not commit runtime-generated assets, SQLite databases, logs, caches, `node_modules`, or built frontend output.
- Test media fixtures must live in `backend/tests/fixtures/`.
- New providers must not hard-code local absolute paths; route storage and fixture access through settings.
- After changing storage, fixture, Docker, provider, or media logic, run `.\scripts\check.ps1`.
- Do not start phase two work in the same broad change as phase-one baseline cleanup.

## Phase Two Order

When phase two begins, develop in this order:

```text
2A: task data model, migrations, and state machine
2B: Fake Provider Server and field mapping
2C: persistent Worker, lease lock, and restart recovery
2D: retry, cancellation, and error classification
2E: safe download, FFprobe validation, and asset registration
2F: frontend task status and Provider capability display
2G: full integration tests and Docker verification
```

Do not modify Worker, Provider, download safety, and frontend task surfaces together without focused tests.

## Test Commands

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

Windows:

```powershell
.\scripts\test.ps1
```

## Before Commit

Run the full test script and verify that no unrelated generated files are included:

```bash
git status --short
./scripts/test.sh
```
