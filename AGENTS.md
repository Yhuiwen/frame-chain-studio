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
- Do not assign `GenerationTask.status` directly. Every task state change must go through `TaskService`.
- Providers must not directly mutate database models. They execute generation capability and return results to orchestration code.
- Phase 2 async providers live behind `AsyncGenerationProvider`; they must not import SQLModel `Session`, read or write `GenerationTask`, change `Shot`, create `Asset`, write `TaskLog`, or perform local task state transitions.
- Providers must return unified DTOs and convert HTTP failures into provider exceptions. Do not pass raw `httpx.Response` objects into services or routes.
- API keys, authorization headers, cookies, tokens, and secrets must never appear in logs, `repr`, response summaries, or database snapshots.
- Provider field mapping must stay declarative and safe. Do not use `eval`, JSONPath engines, Python expressions, or templates that execute code.
- Every new provider must declare capabilities and pass Fake Provider or `httpx.MockTransport` tests.
- Business retries, remote result downloads, Worker loops, and task recovery belong to later orchestration stages, not Provider implementations.
- Future workers must acquire a task lease before processing a task.
- Generation Workers must acquire a database lease before every task execution cycle, and Provider HTTP calls must happen outside database transactions.
- Worker submit and recovery paths must reuse `GenerationTask.idempotency_key` as the Provider `client_request_id`; never generate a new client request ID while recovering `SUBMITTING`.
- `RUNNING` recovery must poll the existing `remote_job_id`, not resubmit.
- Remote Provider success must move tasks to `RESULT_READY`; only a later media and asset stage may complete `RESULT_READY -> SUCCEEDED`.
- Workers must not modify `Shot`, create `Asset`, download media, or perform FFmpeg/FFprobe result processing.
- `max_attempts` counts the first automatic execution plus automatic retries; manual retry creates a new linked task attempt.
- Cancellation API handlers must only record durable intent. Provider cancellation belongs in the Worker.
- Cancellation retries must keep tasks in `CANCELLING`; do not send cancelling tasks through generic `RETRY_WAIT`.
- Manual retry is allowed only from `FAILED` or `CANCELLED`, and must use a durable `TaskCommand` idempotency key.
- Task query payloads may expose sanitized error code/message and control flags, but must not expose raw provider error details.
- Phase 2D does not include result URL download, FFprobe validation, asset registration, Shot advancement, provider settings UI, Redis/Celery/Kafka/APScheduler, WebSocket/SSE, or real vendor APIs.
- Worker tests must cover crash recovery, expired lease takeover, and two-worker lease competition.
- Retry/cancel tests must cover legal and illegal manual retry, cancel idempotency, retry limits, provider cancel failures, and timeout paths.
- Do not perform network requests, FFmpeg work, sleeps, or long-running provider operations inside database transactions.
- Task completion must be idempotent and must not create duplicate result assets.
- New task-model fields require an Alembic migration and migration tests.
- After changing task models or migrations, run migration tests and `.\scripts\check.ps1`.

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
