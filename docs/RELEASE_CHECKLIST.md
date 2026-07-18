# Release Checklist

Use this before creating a `v0.2.0` tag. Do not tag until every required item is true.

- Worktree is clean: `git status --short`.
- Full local verification passes: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1`.
- Alembic is at head: `cd backend; python -m alembic current; python -m alembic heads`.
- Local dev stack starts with `scripts/dev-start.ps1`.
- Local 3 Shot E2E passes, including final render playback and download.
- Services stop cleanly with `scripts/dev-stop.ps1`.
- Docker config passes: `docker compose --profile development --profile worker config --quiet`.
- Docker E2E and restart persistence pass when Docker daemon is available.
- Backup and restore smoke tests pass.
- Runtime data is not staged: SQLite databases, storage, logs, `.run`, `backups`, `dist`, and `node_modules`.
- Provider configs contain no real API keys.
- CI passes on GitHub Actions.
- Known Vite warnings are reviewed and documented.

Suggested commands after all checks pass:

```powershell
git add .
git commit -m "feat: complete v0.2.0 release candidate baseline"
git tag v0.2.0
```

Do not push or create a GitHub Release until the user explicitly requests it.
