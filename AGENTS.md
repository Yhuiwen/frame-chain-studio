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
- `.github/workflows`: CI checks for backend, frontend, and Docker Compose.
- `docs`: release checklist and troubleshooting notes.

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
- Remote Provider success must move tasks to `RESULT_READY`; ResultWorker owns `RESULT_READY -> PROCESSING_RESULT -> SUCCEEDED`.
- Workers must not modify `Shot`, create `Asset`, download media, or perform FFmpeg/FFprobe result processing.
- `max_attempts` counts the first automatic execution plus automatic retries; manual retry creates a new linked task attempt.
- Cancellation API handlers must only record durable intent. Provider cancellation belongs in the Worker.
- Cancellation retries must keep tasks in `CANCELLING`; do not send cancelling tasks through generic `RETRY_WAIT`.
- Manual retry is allowed only from `FAILED` or `CANCELLED`, and must use a durable `TaskCommand` idempotency key.
- Task query payloads may expose sanitized error code/message and control flags, but must not expose raw provider error details.
- Phase 2D does not include result URL download, FFprobe validation, asset registration, Shot advancement, provider settings UI, Redis/Celery/Kafka/APScheduler, WebSocket/SSE, or real vendor APIs.
- Result downloads must validate URL scheme, credentials, fragments, DNS results, and resolved IP addresses before every request.
- Never use automatic redirects for result downloads. Every redirect target must be revalidated, and HTTPS-to-HTTP downgrade must be rejected.
- Result downloads must not send Provider API keys, Authorization headers, Cookie headers, or custom user-supplied headers.
- Result downloads must stream to `.part` files under the configured storage temp directory and enforce byte limits while streaming.
- Local result file names must come from internal IDs and content hashes, not remote file names or `Content-Disposition`.
- Media type must be determined by Pillow or FFprobe validation, not URL suffix or Content-Type alone.
- Result download, FFprobe, file moves, sleeps, and network calls must happen outside database transactions.
- Asset creation from result processing must be idempotent per project, Shot, asset type, and SHA-256.
- Asset identity is revision-aware. The same SHA-256 may exist across different Shot revisions, but current identity must stay unique per project, Shot, asset type, revision, and SHA-256.
- ResultWorker must not directly mutate Shot fields. It must call workflow/service functions that validate Shot transitions.
- Older task results must not overwrite newer task attempts. Stale results should be marked explicitly and skipped before download when detectable.
- API payloads must not expose full result source URLs, presigned query strings, temp paths, storage roots, or local absolute paths.
- `PROCESSING_RESULT` crash recovery and duplicate Worker competition require tests.
- Worker tests must cover crash recovery, expired lease takeover, and two-worker lease competition.
- Retry/cancel tests must cover legal and illegal manual retry, cancel idempotency, retry limits, provider cancel failures, and timeout paths.
- Do not perform network requests, FFmpeg work, sleeps, or long-running provider operations inside database transactions.
- Task completion must be idempotent and must not create duplicate result assets.
- Quality checks are advisory review evidence only. They must be persisted against the current video asset, optional reference asset, check type, and algorithm version; they must not advance, approve, or reject Shots.
- New task-model fields require an Alembic migration and migration tests.
- After changing task models or migrations, run migration tests and `.\scripts\check.ps1`.
- Project Provider defaults may store only safe Provider IDs, model names, aspect ratio, duration, and seed. Never store API keys, base URLs, or raw Provider JSON on `Project`.
- Generation endpoints must resolve effective Provider parameters on the backend and persist the safe effective snapshot before queueing a task.
- Provider capability validation must happen on the backend. Frontend controls may guide the user, but cannot be the only state or capability enforcement.
- Worker heartbeats are best-effort status signals. Heartbeat failures must be logged and ignored so task processing can continue.
- Worker status APIs may expose online state, current task ID, processed count, and sanitized errors, but not local paths, raw Provider config, secrets, or raw result URLs.
- Frontend task views should group attempts by `GenerationRequest`, show actual backend `generation_mode`, and avoid duplicating the full Shot state machine.
- Relative runtime paths must be normalized through backend settings, not process current working directories. API and all Worker processes must share the same database, storage root, fixture root, log root, and Provider config.
- FastAPI startup should use lifespan handlers. Do not add new `@app.on_event` startup hooks.
- `GET /api/ready` must remain safe to expose: no secrets, absolute local paths, Provider API keys, raw Provider config, or storage roots.
- API errors must include the request ID, and responses should return `X-Request-ID`.
- RenderWorker owns `ProjectRender` processing. It must acquire a render lease, run FFmpeg/FFprobe outside database transactions, register a `PROJECT_RENDER` asset, and keep render failures persisted.
- Final project rendering currently strips audio. Do not imply audio mixing, subtitles, watermarking, or timeline effects exist until implemented.
- Media serving must keep path traversal checks and support Range requests for video preview/download.
- Local orchestration scripts may stop only PIDs recorded in `.run/dev-processes.json`; never kill unrelated user processes on common ports.
- Runtime `.run/` and `backups/` output must stay ignored by Git.
- Script import must never directly create formal Shots. Imported text is immutable and must first become ScriptBlocks, StoryboardDrafts, and editable ShotDrafts.
- Script parsing is deterministic rules-based review assistance, not LLM understanding. Preserve source ranges and unrecognized text; do not call LLMs or network services from the parser.
- Do not auto-create Characters, Locations, StyleProfiles, references, or all Shots from script text. Users must explicitly match entities and apply selected ShotDrafts.
- Applying ShotDrafts must be idempotent and must not overwrite existing formal Shots or completed generation results.
- TOAPIS uses the dedicated `ToApisProvider`, fixed provider key `toapis`, official v1 base URL, and `TOAPIS_API_KEY`; never route it through arbitrary mapped fields or persist the secret.
- TOAPIS Vidu Q3 Pro `image_urls` are reserved for ordered start/end anchors. Provider `last_frame_url` is audit-only and never replaces the local FFmpeg locked tail.
- TOAPIS first/last video anchors must be normalized to audited 1280x720 RGB PNG `VIDEO_INPUT_FRAME` assets before upload. Failed paid runs are immutable; recovery requires a separate lineage run, an exact Recovery Plan hash, and new explicit authorization.
- TOAPIS paid two-Shot verification is a persisted `ProviderVerificationRun` state machine. Each advance is short and idempotent, recovery uses the run ID, and Shot 2 must inherit Shot 1's validated local FFmpeg tail asset. `ConfirmLive` never authorizes payment without the independent `ExecutePaid` gate.

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

## Local Dev Orchestration

Preferred local stack:

```powershell
.\scripts\dev-start.ps1
.\scripts\dev-status.ps1
.\scripts\dev-logs.ps1
.\scripts\dev-stop.ps1
```

Use alternate ports if another manual API or frontend is already running:

```powershell
.\scripts\dev-start.ps1 -BackendPort 8100 -FrontendPort 5174 -FakeProviderPort 8091
```

The dev script writes logs and PIDs under `.run/`, generates a local Provider config from `backend/provider-config.example.json`, runs Alembic, and waits for Fake Provider, backend readiness, frontend, and Worker heartbeat status before reporting success.

Back up or restore local SQLite data with:

```powershell
.\scripts\backup.ps1
.\scripts\restore.ps1 -BackupPath .\backups\frame-chain-YYYYmmdd-HHMMSS.db
```

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

Docker configuration checks:

```powershell
docker compose config --quiet
docker compose --profile development --profile worker config --quiet
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

Also run:

```powershell
.\scripts\check.ps1
docker compose --profile development --profile worker config --quiet
```

Do not auto-commit, push, tag, or publish a release unless the user explicitly asks for that operation.
