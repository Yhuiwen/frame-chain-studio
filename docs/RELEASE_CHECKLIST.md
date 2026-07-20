# Release Checklist

- Run `.\scripts\e2e-real-provider.ps1` and confirm the default output reports `BLOCKED_LIVE_VERIFICATION` with all four network-operation flags false.
- Do not claim TOAPIS live image, video, first-last-frame, or two-shot verification without sanitized evidence from an explicitly confirmed cost-bounded run.
- Confirm TOAPIS pricing remains reviewed and unexpired, both target models passed preflight, account capacity was manually confirmed, and the supplied snapshot hash matches before enabling live orchestration.

Use this before creating a `v0.2.0` tag. Do not tag until every required item is true.

- Worktree is clean: `git status --short`.
- Full local verification passes: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1`.
- Alembic is at head: `cd backend; python -m alembic current; python -m alembic heads`.
- Local dev stack starts with `scripts/dev-start.ps1`.
- Isolated local E2E passes: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\e2e-local.ps1 -BackendPort 8100 -FrontendPort 5174 -FakeProviderPort 8091`.
- The E2E JSON summary uses one `project_id` and one `render.id` for the 3 Shot workflow, final render, backup, restore, and restored media verification.
- Local 3 Shot E2E passes, including GenerationWorker restart recovery without duplicate Provider submit, first/last-frame Provider request evidence, quality-check evidence for current video assets, final render playback, full download, Range `206`, and FFprobe verification.
- Structured continuity evidence passes: Character, Location, StyleProfile, ShotSpec history, no-op sync, explicit sync, Prompt Compiler `structured-continuity-v1`, GenerationRequest structured snapshots, and Provider reference Asset injection.
- Script/storyboard evidence passes: script SHA/version, parser `deterministic-script-parser-v1`, ScriptBlock source ranges, editable ShotDrafts, split/merge, manual Character/Location/StyleProfile matching, Prompt preview, batch apply into three Shots, and restored `applied_shot_id` links.
- Provider settings evidence passes: ProviderProfile and ProviderModelProfile CRUD/validation, contract verification, safe `secret_configured` reporting, and no secret values in API payloads.
- Usage and budget evidence passes: request-level estimates, task-attempt estimates, provider-reported actual records, Decimal-string costs, unknown costs shown as `UNKNOWN`/`null`, Fake Provider explicit zero-cost records, budget policy persistence, and CSV export.
- Live real-Provider verification remains blocked by default: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\e2e-real-provider.ps1` prints `BLOCKED_LIVE_VERIFICATION` without network or cost.
- Structured prompt and reference-image behavior remains labeled `CONTRACT_VERIFIED_ONLY`; do not claim live real-Provider visual quality validation.
- E2E summary includes per-Shot `quality_result_count`, `quality_check_types`, `quality_algorithm_versions`, `quality_asset_id`, `asset_revision_count`, and `superseded_asset_count`.
- Backup/restore evidence includes persisted quality-check counts and `quality_duplicate_count = 0`.
- Backup/restore evidence includes readable ScriptDocument, ScriptBlocks, StoryboardDraft, ShotDrafts, and applied Shot links.
- Services stop cleanly with `scripts/dev-stop.ps1`.
- Docker config passes: `docker compose --profile development --profile worker config --quiet`.
- Docker E2E and restart persistence pass when Docker daemon is available.
- Backup and restore smoke tests pass.
- Quality-check warnings/errors are reviewed as advisory reviewer evidence only; they must not be treated as automatic Shot approval or rejection.
- Runtime data is not staged: SQLite databases, storage, logs, `.run`, `backups`, `dist`, and `node_modules`.
- Provider configs and ProviderProfile rows contain no real API keys, authorization headers, cookies, tokens, or secret material.
- CI passes on GitHub Actions.
- Known Vite warnings are reviewed and documented.

Suggested commands after all checks pass. Stage only release-owned source and documentation files; do not use `git add .`.

```powershell
git add backend/app backend/migrations backend/tests frontend/src scripts/e2e-local.ps1 README.md CHANGELOG.md AGENTS.md docs/RELEASE_CHECKLIST.md docs/TROUBLESHOOTING.md
git commit -m "feat: complete v0.2.0 release candidate baseline"
git tag -a v0.2.0 -m "Frame Chain Studio v0.2.0"
```

Do not push or create a GitHub Release until the user explicitly requests it.
