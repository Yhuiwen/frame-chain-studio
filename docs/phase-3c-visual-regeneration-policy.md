# Phase 3C Visual Regeneration Policy

Visual regeneration planning is available at `/projects/:projectId/visual-regeneration`. It is a PlanOnly workflow: it creates deterministic repair proposals and never uploads media, calls a Provider, creates generation tasks, changes a source Run, or grants paid execution authority.

Scopes are `KEYFRAME_ONLY`, `VIDEO_ONLY`, `SHOT_KEYFRAME_AND_VIDEO`, `FROM_SHOT_TO_END`, and `FULL_PROJECT`. Deterministic recommendation rules prefer the smallest safe downstream scope; `FULL_PROJECT` is never the default. Style drift requires rebuilding the affected keyframe and video, an intra-Shot cut requires rebuilding that video with continuous-shot constraints, and scale/composition drift tightens camera and MotionDelta limits. A passed cross-Shot seam is not treated as a repair target.

The Prompt Contract editor separates Character, Camera, Environment, Style, and Motion. Shot 2 inherits the four locks from Shot 1 while retaining its own MotionDelta. The compiler emits a stable Character → Camera → Environment → Style → Motion sequence, negative constraints, audit summary, and prompt hash. It does not accept raw Provider JSON and excludes paths, URLs, credentials, timestamps, and random phrasing.

Keyframe Delta uses real image metrics when assets exist. Before a proposed keyframe exists it reports `PRE_GENERATION_ESTIMATE` with no fabricated SSIM or pHash. `TOO_SIMILAR`, `TOO_DIFFERENT`, and unresolved reuse risk block readiness; excessive motion produces a non-mutating Shot split suggestion.

Cost estimates reuse the reviewed TOAPIS Decimal pricing contract. Estimated and actual billing remain separate, the maximum ceiling is enforced, and stale/mismatched pricing blocks review readiness. Plan hashes include source report hashes, scope, strategy, assets, Prompt Contract and compiled prompt hashes, Delta policy, task counts, durations, estimates, ceiling, pricing snapshot, and plan version. Comments and UI state are excluded.

Human approval means only that the proposal content was reviewed. It requires explicit acknowledgement of visual failures, estimated cost, and zero execution. It does not enable live orchestration, constitute paid authorization, or make `readyForPaidExecution` true.

Run 6 produces two candidates. `MINIMUM_COST_REPAIR` rebuilds Shot 1 keyframe/video and Shot 2 video while conditionally reusing Shot 2’s target; it remains blocked pending real Delta validation and estimates 166.3 credits. `HIGHER_CONTINUITY_REPAIR` rebuilds both keyframes and both videos from local tail lineage, is recommended for review, and estimates 172.6 credits. Both retain the rejected visual conclusion and blocked production gate.

Future paid execution requires a separate, explicit authorization stage with a matching immutable plan hash and budget ceiling.
