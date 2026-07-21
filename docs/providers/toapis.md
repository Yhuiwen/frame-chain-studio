# TOAPIS Provider

Provider key `toapis` uses the fixed base URL `https://toapis.com/v1` and reads its Bearer token only from `TOAPIS_API_KEY`. The application stores and returns the environment-variable name and a boolean `secret_configured`; it never stores or displays the key.

The dedicated adapter uploads JPEG, PNG, and WebP anchors (maximum 10 MB) through `POST /uploads/images`. Seedream 5.0 uses `POST /images/generations` and `GET /images/generations/{task_id}` with remote model `doubao-seedream-5-0`, one 2K output, and no web search or sequential generation. Negative requirements are appended deterministically to the prompt because no separate field is assumed.

Vidu Q3 Pro uses `POST /videos/generations` and `GET /videos/generations/{task_id}` with remote model `viduq3-pro`. Zero images means text-to-video, one means start-frame video, and two means first-last-frame video. For two anchors, `image_urls[0]` is always the start frame and `image_urls[1]` is always the target end frame. Structured Character, Location, and Style references remain in the request snapshot/prompt and are not allowed to consume anchor capacity.

Status mapping is explicit: `queued`/`submitted` to queued, `in_progress`/`processing` to running, `completed` to succeeded, and `failed` to failed. Unknown statuses fail contract parsing. Completed result URLs are untrusted, may expire, and continue through the existing SSRF-safe downloader and media validation. Optional `last_frame_url` is audit metadata only; authoritative continuity uses the locally downloaded video, FFmpeg extraction, human approval, and locked tail frame.

Remote cancellation is not verified. Local cancellation may not stop vendor work or cost. `client_business_id` supports recovery lookup but is not claimed as exactly-once. Actual cost remains unknown unless a verified whitelisted usage field is returned; estimated cost is never copied into actual cost.

Dry run (offline, no upload, submit, poll, network, or fee):

```powershell
.\scripts\e2e-real-provider.ps1
```

Live mode requires both explicit confirmation and a cost ceiling, and reads the key only from the environment:

```powershell
.\scripts\e2e-real-provider.ps1 -ConfirmLive -MaxCost 5.00 -AutoApproveForVerification
```

Current verification state: TOAPIS contract verified; live image, live video, first-last-frame, and two-shot chain are not verified.

## Live enable and accounting units

The reviewed candidate snapshot `toapis-public-2026-07-21` uses Seedream 5.0 at 6.3 `TOAPIS_CREDIT` per `IMAGE_REQUEST` and Vidu Q3 Pro at 20 `TOAPIS_CREDIT` per `VIDEO_SECOND`. Its Decimal estimate is 172.6 credits for two images and eight video-seconds, with a 190-credit verification ceiling. This is reference pricing: actual charging may vary by user group or promotion, and the supplier does not guarantee that the final charge will equal 172.6. First/last-frame requests are reviewed as Vidu Q3 Pro standard generation because they use two ordered `image_urls` and omit `metadata.generation_type=reference2video`; the official API guide does not publish a separate first/last-frame price.

The official documentation index currently links to an OpenAPI 3.1 document whose only paths are the sample `/plants` operations. It does not define TOAPIS models, balances, uploads, images, or videos. Contract decisions are therefore cross-checked against the official endpoint guides, and the incomplete OpenAPI remains a paid-readiness blocker. For Vidu Q3, `seed` is a top-level optional integer, but the first paid verification fixes it to null and omits the field. Video requests include `aspect_ratio` only for text-to-video; one- and two-anchor requests omit it. The Worker validates both ordered anchors with Pillow, rejects EXIF rotation and unsupported dimensions, and rejects ratio differences with `ANCHOR_ASPECT_RATIO_MISMATCH` before any upload.

Run `scripts/create-toapis-verification-anchor.py` to create the ignored local 1280×720 verification anchor. Run `scripts/toapis-paid-readiness.ps1` only after tests; it performs read-only model and balance GETs, reads local gate state, and never enables live orchestration. It emits a suggested paid command only when every gate is true, but never executes that command.

TOAPIS model credits, token `remain_quota`, and USD are distinct fields. The application never assumes a conversion between them. Candidate prices begin `PENDING`; a local operator must review the exact values, run the read-only model-access preflight, confirm sufficient account capacity without storing the balance, and explicitly enable live orchestration. Reviews become stale after the configured maximum age (seven days by default), disabling new submits.
