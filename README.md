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

## Reliable Async Task Model

Phase 2A adds the durable task model needed for future remote providers and workers. It does not add real HTTP providers, file downloads, background worker loops, WebSocket, SSE, or frontend provider configuration.

`GenerationRequest` represents a user's logical generation intent: the Shot, generation kind, prompt snapshots, input assets, output assets, and first-stage compatibility status. A request may have multiple execution attempts.

`GenerationTask` represents one execution attempt for a `GenerationRequest`. Failed or cancelled attempts remain in history; manual retry creates a new task attempt linked by `retry_of_task_id` and `root_task_id`. This keeps historical attempts immutable instead of moving a failed task back to `QUEUED`.

Task statuses:

- `QUEUED`: local task exists and has not started submitting.
- `SUBMITTING`: a future worker is submitting to a provider.
- `RUNNING`: a provider job is running or the Mock Provider is executing locally.
- `RETRY_WAIT`: a retryable error occurred and the task is waiting for the next attempt inside the same execution attempt.
- `SUCCEEDED`: the result has been registered locally.
- `FAILED`: the task reached an unrecoverable error or retry limit.
- `CANCELLING`: cancellation was requested and is awaiting provider acknowledgement.
- `CANCELLED`: the task is cancelled and will not execute.

Allowed task transitions:

```text
QUEUED -> SUBMITTING
QUEUED -> CANCELLED
SUBMITTING -> RUNNING
SUBMITTING -> RETRY_WAIT
SUBMITTING -> FAILED
SUBMITTING -> CANCELLING
SUBMITTING -> CANCELLED
RUNNING -> RUNNING
RUNNING -> RETRY_WAIT
RUNNING -> SUCCEEDED
RUNNING -> FAILED
RUNNING -> CANCELLING
RETRY_WAIT -> QUEUED
RETRY_WAIT -> SUBMITTING
RETRY_WAIT -> CANCELLED
RETRY_WAIT -> FAILED
CANCELLING -> CANCELLED
CANCELLING -> FAILED
CANCELLING -> RUNNING
```

All task transitions must go through `TaskService`, which validates transitions, records `TaskStateChange`, and keeps repeated same-state operations idempotent.

`idempotency_key` has a database uniqueness constraint and prevents duplicate task attempts for the same logical operation. `attempt_number` is the attempt's ordinal number within one logical generation request, starting at 1. `retry_count` is the number of retryable execution failures inside the current attempt.

Lease fields prepare for future multi-worker execution:

- `locked_by`
- `locked_until`
- `lock_acquired_at`
- `lock_version`

Lease acquisition and renewal use short conditional database updates. With SQLite this is a lightweight best-effort coordination mechanism suitable for local development and tests; a production multi-worker deployment should move this to PostgreSQL row-level locking or equivalent lease primitives. Network calls, FFmpeg work, sleeps, and provider execution must not happen inside database transactions.

Request payloads, response summaries, provider snapshots, and error details are saved through a recursive redaction helper. Sensitive keys such as `authorization`, `api_key`, `token`, `cookie`, `password`, and `secret` are replaced with `***REDACTED***`.

## Provider Protocol

Phase 2B adds a database-free asynchronous Provider protocol for future remote AI services. It does not add a Worker loop, automatic polling, result downloads, frontend Provider settings, or any real vendor integration.

`AsyncGenerationProvider` implementations are responsible only for constructing HTTP requests, sending them, parsing remote responses, and returning unified DTOs. They must not access SQLModel sessions, mutate `GenerationTask`, update `Shot`, create `Asset`, write `TaskLog`, or perform task state transitions. `TaskService` remains the owner of durable task state, leases, remote job IDs, errors, and retry metadata.

Provider capabilities are declared with:

- `provider_id`
- `display_name`
- `text_to_image`
- `image_to_image`
- `image_to_video`
- `first_last_frame_video`
- `video_extension`
- `supports_seed`
- `supports_cancel`
- `supports_negative_prompt`
- `max_reference_images`
- `max_duration_seconds`
- `supported_aspect_ratios`
- `supported_output_types`

Unified request DTOs cover image generation and video generation. They carry prompts, negative prompts, dimensions or duration/FPS, seed, reference assets, metadata, and a client request ID. Asset references use HTTP-accessible URLs plus role metadata; they do not carry database sessions or local absolute disk paths.

Provider return DTOs cover submit, job polling, and cancellation. Remote statuses are normalized to `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, or `UNKNOWN`. These are remote status values, not local `GenerationTask.status` values; a later Worker stage will decide how to translate remote progress into local task transitions.

Provider exceptions classify configuration, authentication, rate limit, remote server, network, timeout, invalid response, unsupported capability, job-not-found, and cancellation errors. HTTP 429 and 5xx errors are marked retryable; HTTP 400, 401, and 403 are not retryable by default. Raw response summaries are redacted and length-limited before they can be stored or reported.

`MappedAsyncHttpProvider` is a configurable HTTP client built on `httpx.AsyncClient`. Its field mapper supports safe dotted paths such as `data.task_id`, `result.items.0.url`, and `start_frame.url`; it supports dict keys, numeric list indexes, missing defaults, `null`, underscores, and hyphens. It deliberately does not support `eval`, JSONPath, templates, or arbitrary Python expressions.

Request mapping is declarative:

```json
{
  "fields": {
    "prompt": "input.text",
    "negative_prompt": "input.negative",
    "duration_seconds": "input.duration",
    "start_frame.url": "input.first_frame_url",
    "end_frame.url": "input.last_frame_url",
    "seed": "parameters.seed"
  },
  "fixed_fields": {
    "parameters.output_format": "mp4"
  }
}
```

Response mapping extracts remote job ID, status, progress, result URLs, and error fields. Result URLs may be a string, a string list, or an object list with URL subpaths such as `url`, `download_url`, or `file.url`. The backend does not download those URLs in Phase 2B.

## Fake Provider

The Fake Provider is a local development and test server. It is not a production API and is not started by the main backend.

Start it separately:

```powershell
cd backend
python -m uvicorn fake_provider.app:app --host 127.0.0.1 --port 8090
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8090/fake/v1/health
```

Endpoints:

- `POST /fake/v1/images/generations`
- `POST /fake/v1/videos/generations`
- `GET /fake/v1/jobs/{job_id}`
- `POST /fake/v1/jobs/{job_id}/cancel`
- `GET /fake/v1/results/{job_id}.mp4`
- `GET /fake/v1/results/{job_id}.png`

Scenarios are selected with test headers such as `X-Fake-Scenario`, `X-Fake-Format`, `X-Fake-Running-Polls`, and `X-Fake-Request-Key`. Supported scenarios are `success`, `immediate_success`, `permanent_failure`, `submit_429_once`, `submit_500_once`, `poll_500_once`, `invalid_submit_response`, `invalid_status_response`, `unknown_status`, `cancel_success`, `cancel_not_supported`, `job_not_found`, and `slow_response`.

The Fake Provider supports three response formats:

- Format A: `data.task_id`, `data.status`, `data.output.video_url`
- Format B: `job.id`, `job.state`, `job.outputs[].url`
- Format C: `id`, numeric `status_code`, `result.files[].download_url`

## Provider Configuration

Example config:

```text
backend/provider-config.example.json
```

Runtime loading uses:

```powershell
$env:FCS_PROVIDER_CONFIG_FILE="D:\AIProjects\frame-chain-studio\backend\provider-config.example.json"
```

Provider config may contain `api_key`, but it is modeled as a secret and must not appear in logs, repr output, response summaries, or database snapshots. The current frontend does not edit Provider configuration.

## Database Migrations

Alembic is used for schema upgrades. `SQLModel.metadata.create_all()` remains available only for isolated test fixtures and non-Alembic fallback; it is not the migration mechanism.

Commands:

```powershell
cd backend
python -m alembic current
python -m alembic upgrade head
python -m alembic current
```

To create a future migration after model changes:

```powershell
cd backend
python -m alembic revision -m "describe change"
```

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

The backend startup initializer applies Alembic migrations to the configured database. The default SQLite database path is still `backend/data/frame_chain.db`, and runtime data remains ignored by Git.
