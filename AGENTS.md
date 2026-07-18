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
