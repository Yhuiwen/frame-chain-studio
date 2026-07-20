# Release Checklist

Use this before creating a `v0.2.0` tag. Do not tag until every required item is true.

- Worktree is clean: `git status --short`.
- Full local verification passes: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1`.
- Alembic is at head: `cd backend; python -m alembic current; python -m alembic heads`.
- Local dev stack starts with `scripts/dev-start.ps1`.
- Isolated local E2E passes: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\e2e-local.ps1 -BackendPort 8100 -FrontendPort 5174 -FakeProviderPort 8091`.
- The E2E JSON summary uses one `project_id` and one `render.id` for the 3 Shot workflow, final render, backup, restore, and restored media verification.
- Local 3 Shot E2E passes, including GenerationWorker restart recovery without duplicate Provider submit, first/last-frame Provider request evidence, final render playback, full download, Range `206`, and FFprobe verification.
- Services stop cleanly with `scripts/dev-stop.ps1`.
- Docker config passes: `docker compose --profile development --profile worker config --quiet`.
- Docker E2E and restart persistence pass when Docker daemon is available.
- Backup and restore smoke tests pass.
- Runtime data is not staged: SQLite databases, storage, logs, `.run`, `backups`, `dist`, and `node_modules`.
- Provider configs contain no real API keys.
- CI passes on GitHub Actions.
- Known Vite warnings are reviewed and documented.

Suggested commands after all checks pass. Stage only release-owned source and documentation files; do not use `git add .`.

```powershell
git add backend/app/workers/execution_service.py backend/fake_provider/app.py backend/provider-config.example.json backend/tests/test_fake_provider.py backend/tests/test_generation_worker.py scripts/restore.ps1 scripts/e2e-local.ps1 README.md docs/RELEASE_CHECKLIST.md docs/TROUBLESHOOTING.md
git commit -m "feat: complete v0.2.0 release candidate baseline"
git tag -a v0.2.0 -m "Frame Chain Studio v0.2.0"
```

Do not push or create a GitHub Release until the user explicitly requests it.
