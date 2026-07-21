# Phase 3C Visual Review Workspace

The visual continuity review workspace is available at `/projects/:projectId/visual-review` (with `/visual-review` as a local convenience redirect). It uses the existing application/API trust boundary; this project does not yet contain a separate user or reviewer role system, so no parallel authentication scheme was introduced.

The page keeps technical completion, media validation, lineage continuity, automatic visual analysis, human review, and the production gate visibly separate. Provider completion or a playable render never implies production quality. The backend alone calculates `production_gate_status`; it is allowed only when technical analysis and automatic analysis pass, the human review is approved, and local tail-frame lineage is present.

The timeline renders formal Shot boundaries separately from automatic scene candidates and confirmed intra-Shot anomalies. Its times come from report metrics and media metadata. Reviewers can seek to markers and compare anchors, keyframes, video frames, and scene-cut frames using side-by-side, overlay, slider, limited-frequency blink, difference-blend, and grayscale-edge modes. Images preserve their aspect ratio.

Metrics are grouped into scene cuts, anchor/target matching, camera stability, composition, subject-scale, style, and cross-Shot continuity. The lightweight metrics are heuristics and are not semantic subject recognition. `INCONCLUSIVE` therefore remains production-blocking. Historical reports without a persisted structured Prompt Contract show an explicit warning rather than inventing one.

Human reviews require all confirmation boxes. Rejections require a supported reason, and `OTHER` requires a plain-text comment. Updates use the report hash and update timestamp for optimistic concurrency. Every accepted update creates a separate visual review audit event; it does not alter generation tasks, verification runs, or billing. Run 6's existing rejection is displayed read-only in this phase.

“Re-run offline analysis” invokes only the local analyzer. Identical video/version/config inputs reuse the existing report and preserve its human conclusion. It does not read provider credentials, submit generation work, or incur cost.

Media is addressed only by Asset or report ID. The backend resolves storage paths, rejects traversal and non-image/video Assets, supports MP4 Range responses, sends `nosniff`, and never returns storage paths or provider result URLs. Internal video-frame previews are generated deterministically into ignored runtime cache using video hash, timestamp, and analysis version; they are not registered as Assets.

Run 6 acceptance confirms both reports load, the render is available through Asset 94, the formal boundary is shown near 4.04 seconds, the Shot 2 anomaly is shown near render time 6.083 seconds, the cross-Shot seam remains distinct from the intra-Shot failure, automatic visual status remains failed, human status remains rejected, and the production gate remains blocked.

Safety boundary: the workspace performs no uploads, provider polling, image/video submissions, live enablement, remote task creation, model downloads, or paid generation.
