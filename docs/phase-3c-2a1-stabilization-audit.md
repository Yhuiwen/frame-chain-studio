# Phase 3C-2A.1 stabilization audit

## Database incident

The Phase 3C-2A `scripts/check.ps1` invocation ran pytest without an explicit isolated runtime. FastAPI lifespan tests therefore resolved the default `backend/data/frame_chain.db` URL and applied migration `20260722_0027`. The database was restored by copying the SQLite backup produced before validation, and its mtime was then manually reset. A SQLite backup is a logical reconstruction, so page allocation, freelist state, and other physical metadata may differ even when every logical row is identical.

The pre-run backup and restored production database are not byte-identical. They have identical `sqlite_master` objects, Alembic revision `20260721_0026`, and deterministic hashes for all 39 user tables after explicit column ordering, row ordering, NULL encoding, and canonical serialization. No 0027 visual-review table or fabricated Run 6 review row exists in production. All 84 registered assets exist under the storage root; all 50 assets with recorded SHA-256 evidence match their files.

`scripts/check.ps1` now creates an isolated database, storage root, and log directory under `.run/check`. Pytest establishes an isolated database before application imports, and both the settings model and pytest bootstrap reject a test environment that resolves to the production database with `TEST_DATABASE_POINTS_TO_PRODUCTION`. Migration tests continue to use their own temporary databases. Fake Provider and backup/restore E2E receive explicit isolated database locations.

## Route diff audit

The committed Git diff from `0099d661` to `00c321b0` for `backend/app/api/routes.py` is 65 additions and 2 deletions. The same numstat remains after ignoring end-of-line whitespace and all whitespace, so there is no format-only replacement in the commit. The changes are limited to visual-review imports, Run readiness enrichment, project Run listing, and append-only visual-review GET/POST endpoints. Route registry tests guard duplicate method/path pairs, required legacy routes, and static-route ordering.

The earlier reported `+1554/-1491` count was produced from a transient working-tree line-ending representation, not the committed object diff. No rewrite of commit `00c321b0` was required or performed.
