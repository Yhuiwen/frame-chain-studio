# Live Provider Verification

Real-provider verification is opt-in and cost bounded. The default TOAPIS command is an offline contract check and must print `BLOCKED_LIVE_VERIFICATION` plus four false network-operation flags. Merely having `TOAPIS_API_KEY` set never enables network access.

Confirmed mode requires `-ConfirmLive` and an explicit positive `-MaxCost`. Evidence belongs under `.run/live-provider/`, which is ignored by Git, and must contain only sanitized IDs/hashes, request modes, asset IDs, usage totals, quality counts, render evidence, and timestamps. Never store keys, full remote IDs, signed URLs, full responses/prompts, absolute media paths, balances, or user identity.

Live status must not be marked verified until Seedream image generation/download, two Vidu Q3 two-anchor videos, local locked-tail inheritance, quality checks, render, FFprobe, Range 206, usage records, and budget compliance all actually complete.

Before confirmed execution, explicitly review the exact `toapis-public-2026-07-21` snapshot, verify both target models with the read-only `/models?type=all` preflight, confirm Token capacity through the read-only balance endpoint, and enable the centralized backend live gate only for the paid run. The reviewed two-Shot estimate is 172.6 reference credits and the bounded verification ceiling is 190: use `-BillingUnit TOAPIS_CREDIT -MaxBillingUnits 190 -PricingSnapshotHash <reviewed-hash>`. `-MaxCost` alone is rejected because no USD conversion is assumed. Public pricing may vary by user group or promotion; first/last-frame Vidu is classified as standard generation because `metadata.generation_type=reference2video` is omitted.
