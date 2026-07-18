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

## PowerShell ExecutionPolicy

Run scripts with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-start.ps1`.

## Video Cannot Seek

The media API supports HTTP Range. If seeking fails, verify the rendered Asset URL is `/api/media/{asset_id}` and the response returns `206` for `Range` requests.

## Final Render Fails

Check render worker logs with `scripts/dev-logs.ps1 -Service render-worker`. Common causes are missing input video files, incomplete Shots, or FFmpeg not installed.

## Storage File Missing

Database rows can outlive files if storage is manually deleted. Restore from a matching database and storage backup.
