# Phase 3C visual experiment authorization

This phase freezes a candidate three-dimensional toy product-photography baseline and prepares two auditable experiment packages. It never authorizes or executes paid generation.

## Baseline and locks

Asset 82 is explicitly excluded because it is a flat-cartoon anchor. Assets 83, 89, 87, and 93 are offline candidates; automatic scores are review evidence only. A human must select and approve one verified project image before a baseline becomes effective. Character, camera, environment, and style locks are hashed with the source asset and version. Comments do not affect the hash; a lock, version, or asset change does.

The target is a small red molded-plastic toy robot beside one stationary blue cube on a light-gray studio tabletop. Camera, framing, lighting, material, color treatment, and three-dimensional product-photography style remain fixed. Text, logos, watermarks, extra props, flat illustration, character redesign, cuts, zoom, and reframing are forbidden.

Shot 1 permits only a slow, small head turn toward the cube. Shot 2 starts from the new Shot 1 local FFmpeg tail and permits only a small single-arm movement toward the cube. Walking, scale jumps, cube movement, hard cuts, camera motion, and style changes are forbidden.

## Candidates

- `SHORT_CONTINUITY_CANARY`: 2 image submits, 2 video submits, 2 seconds each, 4 total video seconds. Current contract estimate: 92.6 TOAPIS_CREDIT; recommended maximum: 110.
- `FULL_CONTINUITY_RETEST`: 2 image submits, 2 video submits, 4 seconds each, 8 total video seconds. Current contract estimate: 172.6 TOAPIS_CREDIT; recommended maximum: 190.

SHORT is recommended because this experiment validates visual constraints, not the already-closed provider integration. Short clips reduce drift and loss while preserving the local-tail lineage test. Historical observed billing is evidence only and never replaces the current pricing contract.

`MINIMUM_COST_REPAIR` remains blocked and cannot enter an authorization package. Package hashes cover baseline, prompts, task limits, duration, pricing, and candidate. Baseline review and plan review are independent. `PLAN_REVIEWED` is not `PAID_AUTHORIZED`; this phase never sets `AUTHORIZED` or `readyForPaidExecution=true`.

Any future execution requires a new, explicit natural-language paid authorization containing the experiment, baseline, prompt, pricing, and plan hashes, exact task limits, maximum billing, and no-extra-retry constraint. The final render must run the automatic visual-continuity gate and remain blocked until human visual approval.
