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

## Frozen SHORT review package

The operator independently approved `SHORT_CONTINUITY_CANARY` as plan content. It is frozen to 2 image tasks and 2 video tasks of 2 seconds each, 4 total video seconds, `maxAttemptsPerTask=1`, and `automaticRetryAllowed=false`. Estimated billing is 92.6 TOAPIS_CREDIT with a maximum gate of 110.

- Baseline hash: `c3b32c4ac984b9350c91e206394e37850ec2b1536c12285eff56d4b84de6a88e`
- Prompt Contract hash: `2f2891d30bc2172e331ead0690ea934e2cb260739f0e7f572d1c898a036e81a0`
- Regeneration Plan hash: `e2ee46fa33d085351d1beeb8f4194aeacdd192977991021e55f030c699f2b86c`
- Experiment Plan hash: `4d0ad7e12ed5fa0f2b2d0aa325993d58e24ac867d6a5050b7024f8b6fee78b52`

The package is only `READY_FOR_EXPLICIT_AUTHORIZATION`; it is not paid-authorized. Suggested future authorization text:

> I approved Project 22's three-dimensional toy-photography baseline and selected SHORT_CONTINUITY_CANARY. I authorize one new TOAPIS visual-continuity experiment with at most 2 image tasks and 2 video tasks of 2 seconds each, estimated at 92.6 TOAPIS_CREDIT with a 110 TOAPIS_CREDIT maximum. Each task may be attempted once; no retry, FULL experiment, or other remote task is authorized. Execution must use the approved Baseline, Prompt Contract, Regeneration Plan, and Experiment Plan hashes.

This text is documentation only and has no effect unless the user sends an independent explicit authorization in a later phase.
