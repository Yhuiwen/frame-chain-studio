import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="Frame Chain Studio Fake Provider", version="0.1.0")

JOBS: dict[str, dict[str, Any]] = {}
ATTEMPTS: dict[str, int] = {}
JOBS_BY_IDEMPOTENCY_KEY: dict[str, str] = {}
SUBMIT_CALLS = 0
CREATED_JOBS = 0
CANCEL_CALLS = 0
CANCELLED_JOBS = 0


def _format_response(job: dict[str, Any], response_format: str, base_url: str) -> dict[str, Any]:
    job_id = str(job["id"])
    status = str(job["status"])
    media_ext = "png" if job["kind"] == "image" else "mp4"
    result_url = f"{base_url}/fake/v1/results/{job_id}.{media_ext}"
    if response_format == "B":
        return {"job": {"id": job_id, "state": status.upper(), "outputs": [{"url": result_url}]}}
    if response_format == "C":
        numeric = {"queued": 0, "running": 1, "succeeded": 2, "failed": 3, "cancelled": 4}[status]
        return {"id": job_id, "status_code": numeric, "result": {"files": [{"download_url": result_url}]}}
    output_key = "image_url" if job["kind"] == "image" else "video_url"
    return {"data": {"task_id": job_id, "status": status, "output": {output_key: result_url}}}


def _request_key(path: str, scenario: str, request_key: str | None) -> str:
    return f"{path}:{scenario}:{request_key or 'default'}"


async def _maybe_slow(scenario: str, seconds: str | None) -> None:
    if scenario == "slow_response":
        await asyncio.sleep(float(seconds or "0.2"))


async def _submit(
    request: Request,
    kind: str,
    scenario: str,
    response_format: str,
    running_polls: str | None,
    request_key: str | None,
    slow_seconds: str | None,
) -> JSONResponse:
    global SUBMIT_CALLS, CREATED_JOBS
    await _maybe_slow(scenario, slow_seconds)
    SUBMIT_CALLS += 1
    body = await request.json()
    idempotency_key = request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")
    if not idempotency_key and isinstance(body, dict):
        value = body.get("client_request_id")
        idempotency_key = str(value) if value else None
    if idempotency_key and idempotency_key in JOBS_BY_IDEMPOTENCY_KEY:
        job = JOBS[JOBS_BY_IDEMPOTENCY_KEY[idempotency_key]]
        if job["kind"] != kind:
            return JSONResponse({"error": {"code": "idempotency_conflict"}}, status_code=409)
        return JSONResponse(_format_response(job, response_format, str(request.base_url).rstrip("/")))
    key = _request_key(request.url.path, scenario, request_key)
    ATTEMPTS[key] = ATTEMPTS.get(key, 0) + 1
    if scenario == "submit_429_once" and ATTEMPTS[key] == 1:
        return JSONResponse({"error": {"code": "rate_limited", "message": "try later"}}, status_code=429)
    if scenario == "submit_500_once" and ATTEMPTS[key] == 1:
        return JSONResponse({"error": {"code": "server_error", "message": "temporary"}}, status_code=500)
    if scenario == "invalid_submit_response":
        return JSONResponse({"data": {"status": "queued"}})
    if scenario == "job_not_found":
        return JSONResponse({"error": "not found"}, status_code=404)
    job_id = f"fake-{uuid4()}"
    status = "succeeded" if scenario == "immediate_success" else "queued"
    JOBS[job_id] = {
        "id": job_id,
        "kind": kind,
        "scenario": scenario,
        "status": status,
        "polls": 0,
        "running_polls": int(running_polls or "2"),
        "format": response_format,
        "idempotency_key": idempotency_key,
    }
    CREATED_JOBS += 1
    if idempotency_key:
        JOBS_BY_IDEMPOTENCY_KEY[idempotency_key] = job_id
    return JSONResponse(_format_response(JOBS[job_id], response_format, str(request.base_url).rstrip("/")))


@app.get("/fake/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "fake-provider"}


@app.get("/fake/v1/test/stats")
def test_stats() -> dict[str, object]:
    return {
        "created_jobs": CREATED_JOBS,
        "submit_calls": SUBMIT_CALLS,
        "cancel_calls": CANCEL_CALLS,
        "cancelled_jobs": CANCELLED_JOBS,
        "jobs_by_idempotency_key": dict(JOBS_BY_IDEMPOTENCY_KEY),
    }


@app.post("/fake/v1/test/reset")
def test_reset() -> dict[str, str]:
    global SUBMIT_CALLS, CREATED_JOBS, CANCEL_CALLS, CANCELLED_JOBS
    JOBS.clear()
    ATTEMPTS.clear()
    JOBS_BY_IDEMPOTENCY_KEY.clear()
    SUBMIT_CALLS = 0
    CREATED_JOBS = 0
    CANCEL_CALLS = 0
    CANCELLED_JOBS = 0
    return {"status": "reset"}


@app.post("/fake/v1/images/generations")
async def submit_image(
    request: Request,
    x_fake_scenario: str = Header(default="success"),
    x_fake_format: str = Header(default="A"),
    x_fake_running_polls: str | None = Header(default=None),
    x_fake_request_key: str | None = Header(default=None),
    x_fake_slow_seconds: str | None = Header(default=None),
) -> JSONResponse:
    return await _submit(
        request,
        "image",
        x_fake_scenario,
        x_fake_format,
        x_fake_running_polls,
        x_fake_request_key,
        x_fake_slow_seconds,
    )


@app.post("/fake/v1/videos/generations")
async def submit_video(
    request: Request,
    x_fake_scenario: str = Header(default="success"),
    x_fake_format: str = Header(default="A"),
    x_fake_running_polls: str | None = Header(default=None),
    x_fake_request_key: str | None = Header(default=None),
    x_fake_slow_seconds: str | None = Header(default=None),
) -> JSONResponse:
    return await _submit(
        request,
        "video",
        x_fake_scenario,
        x_fake_format,
        x_fake_running_polls,
        x_fake_request_key,
        x_fake_slow_seconds,
    )


@app.get("/fake/v1/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    x_fake_scenario: str | None = Header(default=None),
    x_fake_slow_seconds: str | None = Header(default=None),
) -> JSONResponse:
    if x_fake_scenario == "job_not_found":
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)
    job = JOBS.get(job_id)
    if job is None:
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)
    scenario = str(x_fake_scenario or job["scenario"])
    await _maybe_slow(scenario, x_fake_slow_seconds)
    job["polls"] = int(job["polls"]) + 1
    if scenario == "poll_500_once" and job["polls"] == 1:
        return JSONResponse({"error": {"code": "temporary"}}, status_code=500)
    if scenario == "invalid_status_response":
        return JSONResponse({"data": {"task_id": job_id}})
    if scenario == "unknown_status":
        job["status"] = "mysterious"
    elif scenario == "permanent_failure" and job["polls"] >= int(job["running_polls"]):
        job["status"] = "failed"
        response = _format_response(job, str(job["format"]), str(request.base_url).rstrip("/"))
        response.setdefault("data", {}).setdefault("error", {"code": "fake_failed", "message": "permanent failure"})
        return JSONResponse(response)
    elif job["status"] not in {"succeeded", "cancelled", "failed"}:
        job["status"] = "succeeded" if job["polls"] > int(job["running_polls"]) else "running"
    return JSONResponse(_format_response(job, str(job["format"]), str(request.base_url).rstrip("/")))


@app.post("/fake/v1/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    x_fake_scenario: str | None = Header(default=None),
) -> JSONResponse:
    global CANCEL_CALLS, CANCELLED_JOBS
    CANCEL_CALLS += 1
    job = JOBS.get(job_id)
    if job is None or x_fake_scenario in {"job_not_found", "cancel_job_not_found"}:
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)
    scenario = str(x_fake_scenario or job["scenario"])
    if scenario == "cancel_not_supported":
        return JSONResponse({"error": {"code": "not_supported"}}, status_code=405)
    if scenario == "cancel_500_once":
        attempts_key = f"cancel:{job_id}"
        ATTEMPTS[attempts_key] = ATTEMPTS.get(attempts_key, 0) + 1
        if ATTEMPTS[attempts_key] == 1:
            return JSONResponse({"error": {"code": "temporary_cancel_error"}}, status_code=500)
    if scenario == "cancel_timeout":
        await asyncio.sleep(0.2)
    if scenario == "cancel_remote_succeeded":
        job["status"] = "succeeded"
        return JSONResponse(_format_response(job, str(job["format"]), str(request.base_url).rstrip("/")))
    if scenario == "cancel_returns_running":
        job["status"] = "running"
        return JSONResponse(_format_response(job, str(job["format"]), str(request.base_url).rstrip("/")))
    if scenario == "cancel_pending_then_cancelled":
        attempts_key = f"cancel-pending:{job_id}"
        ATTEMPTS[attempts_key] = ATTEMPTS.get(attempts_key, 0) + 1
        if ATTEMPTS[attempts_key] == 1:
            job["status"] = "running"
            return JSONResponse(_format_response(job, str(job["format"]), str(request.base_url).rstrip("/")))
    job["status"] = "cancelled"
    CANCELLED_JOBS += 1
    return JSONResponse(_format_response(job, str(job["format"]), str(request.base_url).rstrip("/")))


@app.get("/fake/v1/results/{job_id}.mp4")
def video_result(job_id: str) -> FileResponse:
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="job not found")
    return FileResponse(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mock-video.mp4")


@app.get("/fake/v1/results/{job_id}.png")
def image_result(job_id: str) -> FileResponse:
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="job not found")
    return FileResponse(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mock-keyframe.png")
