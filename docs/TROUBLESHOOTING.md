# Troubleshooting

## Port In Use

Run `scripts/dev-status.ps1` first. The dev scripts only stop PIDs recorded in `.run/dev-processes.json`; they do not kill unrelated Python or Node processes. Change ports with `scripts/dev-start.ps1 -BackendPort 8100 -FrontendPort 5174 -FakeProviderPort 8091`.

## Docker Daemon Not Running

`docker compose config --quiet` can validate YAML without starting containers, but real Docker E2E requires Docker Desktop or a running daemon.

## Worker Offline

Check `/api/workers/status` or `scripts/dev-status.ps1`. Generation, Result, and Render workers report via `WorkerHeartbeat`; they do not expose HTTP ports.

## Provider Config Not Loaded

Relative Provider config paths resolve from the backend root. Use `FCS_PROVIDER_CONFIG_FILE=provider-config.example.json` locally or `provider-config.docker.json` in Compose.

## Result URL Rejected

Result downloads reject private hosts unless `FCS_ENV` is `development` or `test` and `FCS_RESULT_ALLOWED_PRIVATE_HOSTS` explicitly includes the host.

## FFmpeg Or FFprobe Missing

Install FFmpeg and ensure both `ffmpeg` and `ffprobe` are on `PATH`. `/api/ready` checks both.

## Alembic Version Mismatch

Run `cd backend; python -m alembic upgrade head`. The ready endpoint reports migration current/head status.

## SQLite Locked

Stop duplicate local stacks with `scripts/dev-stop.ps1`. Avoid running multiple unrelated API/worker sets against the same SQLite file.

## Frontend Proxy Error

Verify `VITE_API_PROXY_TARGET` points at the active backend port. The dev script sets this automatically.

## Fake Provider Port Mismatch

Use `scripts/dev-start.ps1` so the generated provider config matches the fake provider port.

## Isolated E2E Fails

Run the release-candidate smoke script with unused ports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\e2e-local.ps1 -BackendPort 8100 -FrontendPort 5174 -FakeProviderPort 8091
```

The script creates a self-contained run directory under `.run/e2e/` with its own SQLite database, storage root, Provider config, logs, backups, and PID file. It starts and stops only the PIDs recorded in that run directory. Inspect `logs/*.err.log` and `logs/*.out.log` inside the retained run directory named at the end of the script output.

The script intentionally fails fast when one of the requested ports is already listening. Pick alternate ports instead of stopping unrelated user processes.

## Fake Provider Upload Missing

First/last-frame video requests use the local Fake Provider upload endpoint, `POST /fake/v1/uploads`, and receive local HTTP references from `GET /fake/v1/uploads/{upload_id}`. If video request mapping fails, confirm the generated Provider config includes `upload_endpoint` and that the Fake Provider stats endpoint records submissions with `input.first_frame_url` and, for Shot 2/3, `input.last_frame_url`.

## Backup Restore Evidence Mismatch

For release validation, backup and restore evidence must refer to the same `project_id` and `render.id` that completed the E2E run. Prefer `scripts/e2e-local.ps1` because it performs backup, destructive restore smoke, API restart, restored project/render lookup, and restored media Range verification in one isolated run.

The RC3 E2E summary should also report restored quality-check counts and `quality_duplicate_count = 0`. If these are missing, run Alembic to head and repeat the isolated E2E script instead of reusing an older database.

## Quality Checks Missing

Quality checks run after a current video enters `VIDEO_REVIEW` or after a manual re-run from the API/UI. They require `ffmpeg` and `ffprobe`, the current video file, and any current start/keyframe reference files to be readable under configured storage. Failures are persisted as reviewer-visible check rows or sanitized task logs; local temp paths and storage roots should not appear in API payloads.

Quality checks are advisory. A warning or error does not automatically reject a video, and a clean result does not approve it.

## Duplicate Quality Rows

Current quality-check identity is `(asset_id, reference_asset_id, check_type, algorithm_version)`, with `NULL` reference assets normalized for uniqueness in the migration. If duplicate current rows appear, verify the database has migration `20260720_0009` applied and check for manual inserts that bypassed the application service.

## PowerShell ExecutionPolicy

Run scripts with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-start.ps1`.

## Video Cannot Seek

The media API supports HTTP Range. If seeking fails, verify the rendered Asset URL is `/api/media/{asset_id}` and the response returns `206` for `Range` requests.

## Final Render Fails

Check render worker logs with `scripts/dev-logs.ps1 -Service render-worker`. Common causes are missing input video files, incomplete Shots, or FFmpeg not installed.

## Storage File Missing

Database rows can outlive files if storage is manually deleted. Restore from a matching database and storage backup.
