# Phase 3C SHORT readiness contract

TOAPIS paid readiness requires an explicit verification candidate. It never infers a workflow from the budget, an unrelated switch, or the presence of an anchor.

## Candidate contracts

`SHORT_CONTINUITY_CANARY` freezes 2 image tasks and 2 video tasks at 2 seconds each, for 4 total video seconds. Each task has one attempt and automatic retry is disabled. With the reviewed unit prices, the estimate is calculated with `Decimal` as `6.3 × 2 + 20 × 2 × 2 = 92.6 TOAPIS_CREDIT`; the recommended ceiling is 110.

`LEGACY_FULL_TWO_SHOT` remains a separate contract: 2 image tasks, 2 video tasks at 4 seconds each, 8 total video seconds, an estimate of 172.6, and a ceiling of 190. Failed-run recovery retains its existing lineage budget rules and is not selected by the SHORT candidate.

Use the read-only check with an explicit candidate:

```powershell
.\scripts\toapis-paid-readiness.ps1 `
  -Candidate SHORT_CONTINUITY_CANARY `
  -BillingUnit TOAPIS_CREDIT `
  -PricingSnapshotHash <reviewed-hash> `
  -MaxBillingUnits 110 `
  -BalanceEvidencePrecheck
```

The helper opens SQLite with `mode=ro`. It does not update pricing, balance, live state, or business records. `ready=true` means only that the read-only conditions passed. It is not paid authorization, does not permit a real visual experiment, does not approve visual quality, and never executes a command preview.

The SHORT paid execution entry is intentionally not implemented in this phase. Therefore readiness emits `paidCommandPreviewAvailable=false` and `SHORT_PAID_EXECUTION_ENTRY_NOT_IMPLEMENTED` instead of presenting a misleading command.
