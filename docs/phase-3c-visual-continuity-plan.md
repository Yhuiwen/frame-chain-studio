# Phase 3C: Visual Continuity Plan

## Status and scope

Run 6 passed the technical Provider, persistence, media-processing, and local tail-frame lineage checks. Operator review rejected its production visual quality because of character-style drift, an intra-Shot scene cut, composition discontinuity, and subject-scale drift.

This plan does not authorize Provider calls, uploads, generation tasks, retries, live enablement, or production use. Every future paid experiment requires a new explicit authorization and budget gate.

## Input and prompt controls

1. Use the same three-dimensional toy-photography style for the initial Anchor and every target keyframe. Flat test artwork must not be used as a real-video starting Anchor.
2. Limit the difference between each Shot's first and last keyframes to one small, unambiguous action. Reject endpoints that also change camera, background, lighting, character design, or subject scale.
3. Compile explicit locks for character geometry, face, materials, colors, proportions, and distinguishing details into both image and video prompts.
4. Compile explicit locks for camera position, focal length, framing, background, tabletop, lighting direction, exposure, and color temperature.
5. Treat start/end anchors as immutable ordered controls. A Provider-reported `last_frame_url` remains audit evidence only and must never replace the locally extracted FFmpeg tail frame.

## Automated visual gates

6. Add Shot-internal scene-transition detection. Detect hard cuts and abrupt global histogram, embedding, or optical-flow discontinuities outside the expected formal Shot boundary.
7. Block automatic visual approval when a non-expected hard cut is detected inside a Shot. Technical task success must remain intact and separate.
8. Compare the decoded first frame, decoded last frame, and target keyframe with versioned perceptual-similarity checks.
9. Measure subject position, bounding-box area, dominant colors, and relative robot/cube geometry. Persist thresholds and algorithm versions with the reviewed Asset.
10. Make quality results advisory evidence until calibrated. They may block visual approval, but must not rewrite task success, Run technical status, or local lineage facts.

## Approval model

11. Separate technical approval from visual approval in storage and API payloads. At minimum expose technical Provider status, data-lineage status, final visual-review status, and production readiness independently.
12. A technically passed Run with rejected or pending visual review must never enter a production workflow automatically.
13. Human visual review must reference the exact immutable video/render Asset and record reviewer source, reason codes, notes, and review time.
14. A future paid validation must start from a reviewed 3D Anchor/keyframe set, declare task and billing limits, and obtain explicit authorization before any remote operation.

## Proposed implementation order

1. Define visual-review and automated-check persistence without changing existing technical Run semantics.
2. Add deterministic frame sampling and scene-cut fixtures.
3. Add perceptual, subject-position, scale, and color checks with focused unit tests.
4. Add an operator review surface that clearly separates technical and production decisions.
5. Run offline fixture calibration and document thresholds.
6. Prepare a read-only paid-experiment plan and request separate authorization; do not execute it as part of Phase 3C implementation.

## Exit criteria

- Flat Anchors are rejected for real-video validation.
- No unexpected intra-Shot hard cut is present.
- Character style, material, color, and proportions remain within reviewed tolerances.
- Camera, background, lighting, subject position, and subject scale remain within reviewed tolerances.
- Local FFmpeg tail-frame lineage passes.
- Technical Provider verification and final human visual review both pass independently.
- Billing review is complete and no unauthorized remote task was created.
