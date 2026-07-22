# Phase 3C Provider visual review gates

Provider verification now exposes four independent dimensions. `ProviderVerificationRun.status` remains the technical workflow result. Lineage is calculated from persisted Run, Shot, local tail-frame, inherited start-frame, and final render relationships. Human visual review is an append-only decision bound to an exact Asset ID and SHA-256. Production readiness is a centralized derived result and is never client-writable.

Production is ready only when technical status is `PASSED`, lineage is `PASSED`, the current selected result Asset has an `APPROVED` human review, and no blocking visual evidence remains. `AutoApproveForVerification` continues to mean only `WORKFLOW_VERIFICATION_APPROVAL`; it cannot approve visual quality or production.

The new `ProviderVisualReview` history stores the Run, Project, immutable Asset identity, controlled decision and reason codes, normalized notes, server-owned reviewer source, review time, and optional idempotency key. A review of an older Asset never transfers to a newer selected result Asset. Replaying an identical idempotency key is safe; changing its payload is a conflict.

Historical Run 6 evidence is not rewritten or invented by migration `20260722_0027`. Its existing Asset-bound visual continuity reports are returned as legacy review evidence, preserving:

```text
technical_status=PASSED
lineage_status=PASSED
human_visual_status=REJECTED
production_status=BLOCKED
```

The migration only creates the new review-history table. It performs no network access, media processing, task transitions, Provider operations, live enablement, or paid execution.

## Phase 3C-2A validation incident

During Phase 3C-2A validation, the production SQLite database was unintentionally migrated and then logically restored from the pre-run backup. The restored file was not byte-identical to the original, although schema revision, business rows, registered assets, task state, integrity checks, and deterministic logical hashes matched.

The cause was the unified check entry point running application-lifespan tests without an explicit test database URL. Phase 3C-2A.1 isolates the check runtime under `.run/check`, establishes a separate pytest database before application imports, and rejects `FCS_ENV=test` when it resolves to `backend/data/frame_chain.db`.
