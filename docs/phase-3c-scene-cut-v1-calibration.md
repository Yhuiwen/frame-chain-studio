# Phase 3C scene-cut v1 calibration

`scene-cut-v1` is a deterministic, CPU-only adjacent-frame change detector. It samples decoded video at 12 FPS, scales with nearest-neighbor to 96x54 RGB24, and records timestamps and scores as six-place decimal strings using half-up rounding. Calibration used FFmpeg 8.1.2 on Windows.

## Metrics and thresholds

Pixel delta is the mean absolute RGB byte difference divided by 255. Histogram delta uses 16 fixed bins per RGB channel and is the total absolute bin-count difference divided by six times the pixel count. Both scores are in `[0, 1]`.

The v1 dual-metric rule is:

```text
HARD_CUT when pixel_delta >= 0.250000 AND histogram_delta >= 0.450000
REVIEW_CANDIDATE when pixel_delta >= 0.120000 AND histogram_delta >= 0.200000
```

Two adjacent high-delta boundaries whose surrounding frames return below both review thresholds are downgraded to `REVIEW_CANDIDATE`. This prevents a single-frame white or black flash from being treated as a permanent scene change.

## Synthetic fixture observations

| Fixture | Maximum pixel | Maximum histogram | Hard cuts | Review candidates |
| --- | ---: | ---: | ---: | ---: |
| Static red | 0.000000 | 0.000000 | 0 | 0 |
| Moving testsrc2 | 0.041951 | 0.017233 | 0 | 0 |
| Fade to black | 0.020915 | 0.333333 | 0 | 0 |
| Red/blue crossfade | 0.057516 | 0.666667 | 0 | 0 |
| Red to blue hard cut | 0.660131 | 0.666667 | 1 | 0 |
| Two permanent hard cuts | 0.660131 | 0.666667 | 2 | 0 |
| Hard cut near start | 0.660131 | 0.666667 | 1 | 0 |
| Hard cut near end | 0.660131 | 0.666667 | 1 | 0 |
| Single-frame white flash | 0.662745 | 0.666667 | 0 | 2 |
| Single-frame black frame | 0.329412 | 0.333333 | 0 | 2 |

The maximum no-cut pixel score was `0.057516`. The minimum permanent hard-cut pixel score was `0.660131`; its histogram score was `0.666667`. The selected thresholds sit inside this synthetic separation interval and require both independent metrics. A high histogram delta alone during a smooth fade or crossfade does not produce a hard cut.

## Limits

Maximum analyzed duration is 120 seconds and maximum sampled frames is 1440. Limit, timeout, decode, path, SHA, or frame-size failures persist an incomplete blocking quality result instead of claiming success. Evidence is bound to the exact Asset ID and SHA-256. No original RGB frames, local paths, Provider URLs, credentials, or headers are persisted.

Known limitations include sensitivity to compression, edits spanning less than one 12 FPS interval, rapid camera motion that exceeds both thresholds, and transitions unlike the synthetic fixtures. The return-to-scene rule identifies only single-sample anomalies; it is not semantic scene understanding. Thresholds have not been calibrated against generated Vidu or other real model output and do not replace human review.

```text
CALIBRATION_SCOPE=SYNTHETIC_FIXTURES_ONLY
REAL_GENERATED_VIDEO_CALIBRATION=false
```
