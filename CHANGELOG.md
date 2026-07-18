# Changelog

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
