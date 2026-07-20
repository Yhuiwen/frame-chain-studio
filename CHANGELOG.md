# Changelog

## v0.2.0-rc3

- Adds best-effort video quality-check persistence for review-stage videos: duration, decode health, black/freeze segments, FPS/aspect metadata, tail-target comparison, and start-anchor comparison.
- Keeps quality checks advisory only; they never auto-approve, auto-reject, or advance Shot state.
- Hardens asset identity so identical SHA-256 files can exist across Shot revisions while remaining unique within project, Shot, type, revision, and SHA-256.
- Adds algorithm-versioned quality result identity and E2E backup/restore evidence for quality rows and duplicate-check prevention.
- Extends release validation docs for local-only E2E evidence, backup/restore, Docker config, and known non-blocking warnings.

## v0.2.0-rc2

- Adds Shot `spec_revision`, explicit approved keyframe/video/tail-frame pointers, Asset lifecycle status, and GenerationRequest revision snapshots.
- Prevents stale asynchronous results from advancing Shots or replacing current approved assets.
- Rebuilds continuity inheritance after reordering or anchor changes and invalidates downstream video/tail results.
- Adds safe project image upload plus start-frame and target-keyframe APIs.
- Tightens final render inputs to current approved video assets only.
- Adds `/tasks` and frontend display for revisions, asset validity, continuity sources, task actions, and manual image anchors.

## v0.2.0-rc

- Adds provider-driven generation settings, worker status visibility, and durable Worker heartbeats.
- Adds unified backend-root path resolution for SQLite, storage, fixtures, logs, and Provider config.
- Adds FastAPI lifespan startup and `/api/ready`.
- Adds durable `ProjectRender` jobs, RenderWorker, FFmpeg normalization, concat export, final render Asset registration, and HTTP Range media playback.
- Adds local dev orchestration scripts, SQLite backup/restore scripts, Docker worker/development profiles, and GitHub Actions CI.

This is a release-candidate baseline. No `v0.2.0` tag is created by this changelog.

## v0.1.0

- First complete mock generation workflow with projects, Shots, keyframe review, video review, tail-frame extraction, and start-frame inheritance.
- Persistent generation requests, assets, logs, and state changes.
