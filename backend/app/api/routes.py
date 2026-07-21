from pathlib import Path
from datetime import datetime
from decimal import Decimal
import tempfile

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import BACKEND_ROOT, get_settings
from app.core.errors import AppError
from app.db import engine, get_session
from app.media.ffmpeg import require_binary
from app.models.entities import (
    Asset,
    GenerationKind,
    GenerationRequest,
    Project,
    ProjectRender,
    ProviderVerificationRun,
    ProviderVerificationType,
    Shot,
    TaskCommandType,
    VisualContinuityReport,
)
from app.models.schemas import (
    CharacterCreate,
    CharacterRead,
    CharacterReferenceCreate,
    CharacterReferenceRead,
    CharacterUpdate,
    GenerationStartRequest,
    GenerationRequestRead,
    GenerationUsageRecordRead,
    LocationCreate,
    LocationRead,
    LocationReferenceCreate,
    LocationReferenceRead,
    LocationUpdate,
    ProjectCreate,
    ProjectBudgetPolicyRead,
    ProjectBudgetPolicyUpdate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
    ReorderShot,
    ScriptBlockRead,
    ScriptBlockUpdate,
    ScriptContentRead,
    ScriptDocumentRead,
    ScriptImportRequest,
    ScriptParseRead,
    ShotCreate,
    ShotDraftApplyRequest,
    ShotDraftPreviewRead,
    ShotDraftRead,
    ShotDraftSplitRequest,
    ShotDraftUpdate,
    ShotRead,
    ShotSpecRead,
    ShotSpecRevisionRequest,
    ShotSpecSyncRequest,
    ShotRevisionRead,
    ShotRevisionRequest,
    ShotStartFrameRequest,
    ShotTargetKeyframeRequest,
    ShotUpdate,
    StoryboardApplyRead,
    StoryboardApplyRequest,
    StoryboardCreate,
    StoryboardRead,
    StoryboardUpdate,
    StyleProfileCreate,
    StyleProfileRead,
    StyleProfileUpdate,
    TaskCancelRequest,
    TaskRetryRequest,
    GenerationTaskRead,
    ProjectRenderCreate,
    ProjectRenderRead,
    WorkersStatusRead,
    QualityCheckResultRead,
    LiveVerificationRequest,
    ProviderModelProfileCreate,
    ProviderModelProfileRead,
    ProviderModelProfileUpdate,
    ProviderProfileCreate,
    ProviderProfileRead,
    ProviderProfileUpdate,
    ProviderValidationRead,
    ProviderVerificationRunRead,
    ProviderVerificationAdvanceRead,
    ToApisAccountBalanceRequest,
    ToApisCanaryRecoveryRequest,
    ToApisFailedRunRecoveryRequest,
    ToApisVideoCanaryConsoleReviewRequest,
    ToApisLiveEnableRequest,
    ToApisPricingReviewRequest,
    UsageSummaryRead,
    VisualContinuityAnalyzeRequest,
    VisualContinuityHumanReviewRequest,
    VisualContinuityReportRead,
)
from app.providers.config_loader import load_registry, load_registry_from_env
from app.providers.exceptions import ProviderError
from app.providers.models import ProviderCapabilities, ProviderInfo
from app.providers.mock import MockGenerationProvider
from app.models.entities import ShotDraftStatus
from app.services import (
    live_orchestration,
    provider_management,
    provider_resolution,
    quality_service,
    script_workflow,
    studio,
    structured,
    task_service,
    toapis_canary,
    toapis_canary_recovery,
    toapis_recovery_planning,
    toapis_verification,
    toapis_video_canary,
    visual_continuity_service,
    worker_status,
)
from app.workers import render_service

router = APIRouter()
provider = MockGenerationProvider()


def run_request_in_background(request_id: int) -> None:
    with Session(engine) as session:
        studio.run_generation_request(session, request_id, provider)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    settings = get_settings()
    checks: dict[str, object] = {}
    status = "ready"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_revision()
        head = _alembic_head_revision()
        checks["database"] = "ok"
        checks["migration"] = {"current": current, "head": head, "ok": current == head}
        if current != head:
            status = "not_ready"
    except Exception as exc:
        checks["database"] = f"failed:{exc.__class__.__name__}"
        status = "not_ready"
    try:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.storage_dir, delete=True) as handle:
            handle.write(b"ok")
        checks["storage"] = "ok"
    except Exception as exc:
        checks["storage"] = f"failed:{exc.__class__.__name__}"
        status = "not_ready"
    for binary in ("ffmpeg", "ffprobe"):
        try:
            require_binary(binary)
            checks[binary] = "ok"
        except Exception as exc:
            checks[binary] = f"failed:{exc.__class__.__name__}"
            status = "not_ready"
    try:
        providers = provider_resolution.list_public_providers(load_registry_from_env())
        checks["providers"] = {
            "configured": [provider.provider_id for provider in providers if provider.configured],
            "errors": [provider.provider_id for provider in providers if not provider.configured],
        }
    except Exception as exc:
        checks["providers"] = f"failed:{exc.__class__.__name__}"
        status = "not_ready"
    return JSONResponse(
        status_code=200 if status == "ready" else 503,
        content={"status": status, "checks": checks, "config": settings.safe_summary()},
    )


def _alembic_head_revision() -> str | None:
    alembic_ini = BACKEND_ROOT / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


@router.get("/providers", response_model=list[ProviderInfo])
def list_providers(session: Session = Depends(get_session)) -> list[ProviderInfo]:
    try:
        return provider_resolution.list_public_providers(load_registry(session))
    except ProviderError as exc:
        return [
            ProviderInfo(
                provider_id="configured-provider",
                display_name="Configured Provider",
                capabilities=ProviderCapabilities(
                    provider_id="configured-provider",
                    display_name="Configured Provider",
                ),
                configured=False,
                configuration_error=exc.message,
            )
        ]


@router.get("/provider-profiles", response_model=list[ProviderProfileRead])
def list_provider_profiles(
    include_archived: bool = False,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return provider_management.list_provider_profiles(session, include_archived=include_archived)


@router.get("/provider-profiles/toapis/pricing-review")
def get_toapis_pricing_review(session: Session = Depends(get_session)) -> dict[str, object]:
    return live_orchestration.pricing_review_state(session)


@router.post("/provider-profiles/toapis/pricing-review")
def review_toapis_pricing(
    payload: ToApisPricingReviewRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    return live_orchestration.review_pricing(session, payload)


@router.post("/provider-profiles/toapis/preflight")
async def preflight_toapis(session: Session = Depends(get_session)) -> dict[str, object]:
    return await live_orchestration.run_preflight(session)


@router.post("/provider-profiles/toapis/account-balance-review")
def confirm_toapis_account_balance(
    payload: ToApisAccountBalanceRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    return live_orchestration.confirm_account_balance(session, payload)


@router.post("/provider-profiles/toapis/live-enable")
def enable_toapis_live(
    payload: ToApisLiveEnableRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    return live_orchestration.enable_live(session, payload)


@router.post("/provider-profiles/toapis/live-disable")
def disable_toapis_live(session: Session = Depends(get_session)) -> dict[str, object]:
    return live_orchestration.disable_live(session)


@router.post("/provider-profiles", response_model=ProviderProfileRead)
def create_provider_profile(
    payload: ProviderProfileCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return provider_management.create_provider_profile(session, payload)


@router.get("/provider-profiles/{provider_id}", response_model=ProviderProfileRead)
def get_provider_profile(
    provider_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    profile = provider_management.get_provider_profile_or_404(session, provider_id)
    return provider_management.provider_profile_payload(session, profile)


@router.patch("/provider-profiles/{provider_id}", response_model=ProviderProfileRead)
def update_provider_profile(
    provider_id: int,
    payload: ProviderProfileUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return provider_management.update_provider_profile(session, provider_id, payload)


@router.post("/provider-profiles/{provider_id}/archive", response_model=ProviderProfileRead)
def archive_provider_profile(
    provider_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return provider_management.archive_provider_profile(session, provider_id)


@router.post("/provider-profiles/{provider_id}/validate", response_model=ProviderValidationRead)
def validate_provider_profile(
    provider_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return provider_management.validate_provider_profile(session, provider_id)


@router.post(
    "/provider-profiles/{provider_id}/verify-contract", response_model=ProviderVerificationRunRead
)
def verify_provider_contract(
    provider_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return provider_management.verify_contract(session, provider_id)


@router.post(
    "/provider-profiles/{provider_id}/verify-live",
    response_model=ProviderVerificationRunRead,
    status_code=202,
)
def verify_provider_live(
    provider_id: int,
    payload: LiveVerificationRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return provider_management.verify_live(session, provider_id, payload)


@router.get("/provider-verification-runs/{run_id}", response_model=ProviderVerificationRunRead)
def get_provider_verification_run(
    run_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return provider_management.get_verification_run(session, run_id)


@router.post(
    "/provider-verification-runs/{run_id}/advance", response_model=ProviderVerificationAdvanceRead
)
def advance_provider_verification_run(
    run_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    run = session.get(ProviderVerificationRun, run_id)
    if run and run.verification_type == ProviderVerificationType.LIVE_CANARY:
        return toapis_canary.advance(session, run_id)
    if run and run.verification_type == ProviderVerificationType.LIVE_VIDEO_CANARY:
        return toapis_video_canary.advance(session, run_id)
    return toapis_verification.advance(session, run_id)


@router.post("/provider-verification-runs/{run_id}/recover-existing-canary-result")
def recover_existing_canary_result(
    run_id: int,
    payload: ToApisCanaryRecoveryRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return toapis_canary_recovery.prepare_existing_result_recovery(
        session,
        run_id=run_id,
        existing_remote_task_id=payload.existing_remote_task_id,
        existing_result_url=payload.existing_result_url,
        acknowledged=payload.acknowledge_existing_task_recovery,
    )


@router.post(
    "/provider-verification-runs/{run_id}/start-failed-run-recovery",
    response_model=ProviderVerificationRunRead,
    status_code=202,
)
def start_failed_run_recovery(
    run_id: int,
    payload: ToApisFailedRunRecoveryRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if (
        not payload.acknowledged
        or payload.billing_unit != "TOAPIS_CREDIT"
        or payload.estimated_remaining_billing_units != Decimal("166.3")
        or payload.maximum_lineage_billing_units != Decimal("190")
    ):
        raise AppError(
            "RECOVERY_AUTHORIZATION_INVALID",
            "The failed-run recovery authorization is invalid.",
            409,
        )
    recovery = toapis_recovery_planning.start_authorized_recovery_run(
        session,
        failed_run_id=run_id,
        recovery_plan_hash=payload.recovery_plan_hash,
        authorization_reference=payload.authorization_reference,
    )
    return provider_management.verification_payload(recovery)


@router.post("/provider-verification-runs/{run_id}/video-canary-console-review")
def review_video_canary_console(
    run_id: int,
    payload: ToApisVideoCanaryConsoleReviewRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return toapis_canary_recovery.review_video_canary_console_billing(
        session, run_id=run_id, payload=payload
    )


@router.post(
    "/provider-verification-runs/{run_id}/initial-anchor",
    response_model=ProviderVerificationAdvanceRead,
)
async def set_provider_verification_initial_anchor(
    run_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return toapis_verification.set_initial_anchor(
        session,
        run_id,
        content=await file.read(get_settings().upload_max_image_bytes + 1),
        content_type=file.content_type,
    )


@router.get(
    "/provider-profiles/{provider_id}/models", response_model=list[ProviderModelProfileRead]
)
def list_provider_models(
    provider_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return provider_management.list_provider_models(session, provider_id)


@router.post("/provider-profiles/{provider_id}/models", response_model=ProviderModelProfileRead)
def create_provider_model(
    provider_id: int,
    payload: ProviderModelProfileCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return provider_management.create_provider_model(session, provider_id, payload)


@router.patch("/provider-models/{model_id}", response_model=ProviderModelProfileRead)
def update_provider_model(
    model_id: int,
    payload: ProviderModelProfileUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return provider_management.update_provider_model(session, model_id, payload)


@router.post("/provider-models/{model_id}/archive", response_model=ProviderModelProfileRead)
def archive_provider_model(
    model_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return provider_management.archive_provider_model(session, model_id)


@router.get("/workers/status", response_model=WorkersStatusRead)
def workers_status(session: Session = Depends(get_session)) -> dict[str, object]:
    settings = get_settings()
    return worker_status.status_summary(
        session, stale_after_seconds=settings.worker_stale_after_seconds
    )


@router.get("/projects/{project_id}/usage/summary", response_model=UsageSummaryRead)
def project_usage_summary(
    project_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return provider_management.usage_summary(session, project_id)


@router.get("/projects/{project_id}/usage/records", response_model=list[GenerationUsageRecordRead])
def project_usage_records(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return provider_management.usage_records(session, project_id)


@router.get(
    "/generation-requests/{request_id}/usage", response_model=list[GenerationUsageRecordRead]
)
def generation_request_usage(
    request_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return provider_management.request_usage(session, request_id)


@router.get("/projects/{project_id}/budget", response_model=ProjectBudgetPolicyRead)
def project_budget(project_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return provider_management.budget_for_project(session, project_id)


@router.put("/projects/{project_id}/budget", response_model=ProjectBudgetPolicyRead)
def update_project_budget(
    project_id: int,
    payload: ProjectBudgetPolicyUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return provider_management.update_budget(session, project_id, payload)


@router.get("/projects/{project_id}/usage/export.csv", response_class=PlainTextResponse)
def export_project_usage(
    project_id: int, session: Session = Depends(get_session)
) -> PlainTextResponse:
    return PlainTextResponse(
        provider_management.usage_csv(session, project_id),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}-usage.csv"'},
    )


@router.get("/tasks", response_model=list[GenerationTaskRead])
def list_tasks(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    tasks = task_service.list_all_tasks(session)
    return [studio.task_payload(session, task) for task in tasks]


@router.post("/tasks/{task_id}/cancel", response_model=GenerationTaskRead)
def cancel_task(
    task_id: int,
    payload: TaskCancelRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    task_service.create_or_get_command(
        session,
        task_id=task_id,
        command_type=TaskCommandType.CANCEL,
        idempotency_key=idempotency_key or f"cancel:{task_id}",
        reason=payload.reason if payload else "",
    )
    task = task_service.request_task_cancel(
        session,
        task_id,
        reason=payload.reason if payload else "",
        cancellation_timeout_seconds=120,
    )
    return studio.task_payload(session, task)


@router.post("/tasks/{task_id}/retry", response_model=GenerationTaskRead)
def retry_task(
    task_id: int,
    payload: TaskRetryRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    retry = task_service.manual_retry_task(
        session,
        task_id,
        idempotency_key=idempotency_key or f"retry:{task_id}:{datetime.now().timestamp()}",
        reason=payload.reason if payload else "",
    )
    return studio.task_payload(session, retry)


@router.get("/projects/{project_id}/renders", response_model=list[ProjectRenderRead])
def list_project_renders(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    studio.get_project_or_404(session, project_id)
    return [
        studio.render_payload(render) for render in studio.list_project_renders(session, project_id)
    ]


@router.post("/projects/{project_id}/renders", response_model=ProjectRenderRead, status_code=202)
def create_project_render(
    project_id: int,
    payload: ProjectRenderCreate | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    render = render_service.create_project_render(
        session,
        project_id=project_id,
        idempotency_key=idempotency_key
        or f"project-render:{project_id}:{datetime.now().timestamp()}",
        allow_partial_render=payload.allow_partial_render if payload else False,
    )
    return studio.render_payload(render)


@router.get("/renders/{render_id}", response_model=ProjectRenderRead)
def read_project_render(
    render_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    render = session.get(ProjectRender, render_id)
    if render is None:
        raise AppError("RENDER_NOT_FOUND", f"Render {render_id} was not found.", 404)
    return studio.render_payload(render)


@router.get("/media/{asset_id}", response_model=None)
def read_asset(
    asset_id: int, request: Request, session: Session = Depends(get_session)
) -> Response:
    return asset_response(asset_id, session=session, range_header=request.headers.get("range"))


def asset_response(asset_id: int, *, session: Session, range_header: str | None = None) -> Response:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise AppError("ASSET_NOT_FOUND", f"Asset {asset_id} was not found.", 404)
    settings = get_settings()
    storage_root = settings.storage_dir.resolve()
    asset_path = Path(asset.path).resolve()
    if storage_root not in asset_path.parents and asset_path != storage_root:
        raise AppError(
            "ASSET_ACCESS_DENIED", "Asset file is outside the configured storage directory.", 403
        )
    if not asset_path.exists() or not asset_path.is_file():
        raise AppError("ASSET_FILE_NOT_FOUND", f"Asset file for {asset_id} was not found.", 404)
    if range_header:
        return _range_response(asset_path, asset.mime_type, range_header)
    return FileResponse(asset_path, media_type=asset.mime_type)


def _range_response(path: Path, mime_type: str, range_header: str) -> StreamingResponse:
    size = path.stat().st_size
    parsed = _parse_range(range_header, size)
    if parsed is None:
        return StreamingResponse(
            iter(()),
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
            media_type=mime_type,
        )
    start, end = parsed
    length = end - start + 1

    def iterator():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iterator(),
        status_code=206,
        media_type=mime_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


def _parse_range(value: str, size: int) -> tuple[int, int] | None:
    if not value.startswith("bytes=") or "," in value:
        return None
    spec = value.removeprefix("bytes=").strip()
    if "-" not in spec or size <= 0:
        return None
    start_text, end_text = spec.split("-", 1)
    try:
        if start_text == "":
            suffix = int(end_text)
            if suffix <= 0:
                return None
            start = max(size - suffix, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= size:
        return None
    return start, min(end, size - 1)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return studio.list_projects(session)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    return studio.create_project(session, payload)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def project_detail(project_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    project, shots, assets, requests, tasks, renders, completion, quality_checks, logs = (
        studio.project_detail(session, project_id)
    )
    return {
        **ProjectRead.model_validate(project).model_dump(),
        "shots": shots,
        "assets": assets,
        "requests": requests,
        "tasks": tasks,
        "renders": renders,
        "quality_checks": quality_checks,
        "completion": completion,
        "logs": logs,
    }


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, payload: ProjectUpdate, session: Session = Depends(get_session)
) -> Project:
    return studio.update_project(session, project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> Response:
    studio.delete_project(session, project_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/shots", response_model=list[ShotRead])
def list_shots(project_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [
        studio.shot_payload(session, shot)
        for shot in studio.list_project_shots(session, project_id)
    ]


@router.post("/projects/{project_id}/shots", response_model=ShotRead, status_code=201)
def create_shot(
    project_id: int, payload: ShotCreate, session: Session = Depends(get_session)
) -> Shot:
    return studio.create_shot(session, project_id, payload)


@router.post("/projects/{project_id}/assets/images", response_model=dict, status_code=201)
async def upload_project_image(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    content = await file.read()
    asset = studio.create_project_image_asset(
        session,
        project_id,
        content=content,
        content_type=file.content_type,
    )
    return studio.asset_payload(asset)


@router.get("/projects/{project_id}/scripts", response_model=list[ScriptDocumentRead])
def list_project_scripts(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return script_workflow.list_scripts(session, project_id)


@router.post(
    "/projects/{project_id}/scripts/import", response_model=ScriptDocumentRead, status_code=201
)
async def import_project_script(
    project_id: int,
    request: Request,
    file: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        if file is None:
            raise AppError("SCRIPT_FILE_REQUIRED", "Multipart import requires a file.", 400)
        content = await file.read()
        text, source_type = script_workflow.decode_script_upload(
            content,
            filename=file.filename or "",
            mime_type=file.content_type or "",
        )
        payload = ScriptImportRequest(title=None, source_type=source_type)
        return script_workflow.import_script(
            session,
            project_id,
            payload,
            raw_text=text,
            source_type=source_type,
            original_filename=file.filename or "",
            mime_type=file.content_type or "",
        )
    body = await request.json()
    payload = ScriptImportRequest.model_validate(body)
    return script_workflow.import_script(session, project_id, payload)


@router.get("/scripts/{script_id}", response_model=ScriptDocumentRead)
def read_script(script_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return script_workflow.script_document_payload(
        session, script_workflow.get_script_or_404(session, script_id)
    )


@router.get("/scripts/{script_id}/content", response_model=ScriptContentRead)
def read_script_content(
    script_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    script = script_workflow.get_script_or_404(session, script_id)
    return {
        "id": script.id,
        "title": script.title,
        "raw_text": script.raw_text,
        "content_sha256": script.content_sha256,
        "version": script.version,
    }


@router.post("/scripts/{script_id}/parse", response_model=ScriptParseRead)
def parse_script(script_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return script_workflow.parse_script_document(session, script_id)


@router.get("/scripts/{script_id}/blocks", response_model=list[ScriptBlockRead])
def list_script_blocks(
    script_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return script_workflow.list_blocks(session, script_id)


@router.post("/scripts/{script_id}/versions", response_model=ScriptDocumentRead, status_code=201)
def create_script_version(
    script_id: int,
    payload: ScriptImportRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    parent = script_workflow.get_script_or_404(session, script_id)
    payload.parent_document_id = script_id
    payload.create_new_version = True
    return script_workflow.import_script(session, parent.project_id, payload)


@router.post("/scripts/{script_id}/archive", response_model=ScriptDocumentRead)
def archive_script(script_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return script_workflow.archive_script(session, script_id)


@router.patch("/script-blocks/{block_id}", response_model=ScriptBlockRead)
def update_script_block(
    block_id: int,
    payload: ScriptBlockUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return script_workflow.update_block(session, block_id, payload)


@router.get("/scripts/{script_id}/storyboards", response_model=list[StoryboardRead])
def list_script_storyboards(
    script_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return script_workflow.list_storyboards(session, script_id)


@router.post("/scripts/{script_id}/storyboards", response_model=StoryboardRead, status_code=201)
def create_script_storyboard(
    script_id: int,
    payload: StoryboardCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return script_workflow.create_storyboard(session, script_id, payload)


@router.get("/storyboards/{storyboard_id}", response_model=StoryboardRead)
def read_storyboard(
    storyboard_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return script_workflow.storyboard_payload(
        session, script_workflow.get_storyboard_or_404(session, storyboard_id)
    )


@router.patch("/storyboards/{storyboard_id}", response_model=StoryboardRead)
def update_storyboard(
    storyboard_id: int,
    payload: StoryboardUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return script_workflow.update_storyboard(session, storyboard_id, payload)


@router.post("/storyboards/{storyboard_id}/apply", response_model=StoryboardApplyRead)
def apply_storyboard(
    storyboard_id: int,
    payload: StoryboardApplyRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return script_workflow.apply_storyboard(session, storyboard_id, payload)


@router.post("/storyboards/{storyboard_id}/archive", response_model=StoryboardRead)
def archive_storyboard(
    storyboard_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return script_workflow.archive_storyboard(session, storyboard_id)


@router.get("/storyboards/{storyboard_id}/shot-drafts", response_model=list[ShotDraftRead])
def list_storyboard_shot_drafts(
    storyboard_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return script_workflow.list_shot_drafts(session, storyboard_id)


@router.patch("/shot-drafts/{shot_draft_id}", response_model=ShotDraftRead)
def update_shot_draft(
    shot_draft_id: int,
    payload: ShotDraftUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return script_workflow.update_shot_draft(session, shot_draft_id, payload)


@router.post("/shot-drafts/{shot_draft_id}/split", response_model=list[ShotDraftRead])
def split_shot_draft(
    shot_draft_id: int,
    payload: ShotDraftSplitRequest,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return script_workflow.split_shot_draft(session, shot_draft_id, payload)


@router.post("/shot-drafts/{shot_draft_id}/merge-next", response_model=ShotDraftRead)
def merge_shot_draft_next(
    shot_draft_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return script_workflow.merge_shot_draft_next(session, shot_draft_id)


@router.post("/shot-drafts/{shot_draft_id}/skip", response_model=ShotDraftRead)
def skip_shot_draft(
    shot_draft_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return script_workflow.set_shot_draft_status(session, shot_draft_id, ShotDraftStatus.SKIPPED)


@router.post("/shot-drafts/{shot_draft_id}/restore", response_model=ShotDraftRead)
def restore_shot_draft(
    shot_draft_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return script_workflow.set_shot_draft_status(session, shot_draft_id, ShotDraftStatus.DRAFT)


@router.post("/shot-drafts/{shot_draft_id}/preview-spec", response_model=ShotDraftPreviewRead)
def preview_shot_draft(
    shot_draft_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return script_workflow.preview_shot_draft(session, shot_draft_id)


@router.post("/shot-drafts/{shot_draft_id}/apply", response_model=ShotDraftRead)
def apply_shot_draft(
    shot_draft_id: int,
    payload: ShotDraftApplyRequest | None = None,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return script_workflow.apply_shot_draft(
        session, shot_draft_id, payload or ShotDraftApplyRequest()
    )


@router.get("/projects/{project_id}/characters", response_model=list[CharacterRead])
def list_project_characters(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return structured.list_characters(session, project_id)


@router.post("/projects/{project_id}/characters", response_model=CharacterRead, status_code=201)
def create_project_character(
    project_id: int,
    payload: CharacterCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.create_character(session, project_id, payload)


@router.get("/characters/{character_id}", response_model=CharacterRead)
def read_character(character_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return structured.get_character_payload(session, character_id)


@router.patch("/characters/{character_id}", response_model=CharacterRead)
def update_character(
    character_id: int,
    payload: CharacterUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.update_character(session, character_id, payload)


@router.delete("/characters/{character_id}", status_code=204)
def delete_character(character_id: int, session: Session = Depends(get_session)) -> Response:
    structured.archive_character(session, character_id)
    return Response(status_code=204)


@router.post(
    "/characters/{character_id}/references", response_model=CharacterReferenceRead, status_code=201
)
def create_character_reference(
    character_id: int,
    payload: CharacterReferenceCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.add_character_reference(session, character_id, payload)


@router.delete("/character-references/{reference_id}", status_code=204)
def delete_character_reference(
    reference_id: int, session: Session = Depends(get_session)
) -> Response:
    structured.delete_character_reference(session, reference_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/locations", response_model=list[LocationRead])
def list_project_locations(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return structured.list_locations(session, project_id)


@router.post("/projects/{project_id}/locations", response_model=LocationRead, status_code=201)
def create_project_location(
    project_id: int,
    payload: LocationCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.create_location(session, project_id, payload)


@router.get("/locations/{location_id}", response_model=LocationRead)
def read_location(location_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return structured.get_location_payload(session, location_id)


@router.patch("/locations/{location_id}", response_model=LocationRead)
def update_location(
    location_id: int,
    payload: LocationUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.update_location(session, location_id, payload)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: int, session: Session = Depends(get_session)) -> Response:
    structured.archive_location(session, location_id)
    return Response(status_code=204)


@router.post(
    "/locations/{location_id}/references", response_model=LocationReferenceRead, status_code=201
)
def create_location_reference(
    location_id: int,
    payload: LocationReferenceCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.add_location_reference(session, location_id, payload)


@router.delete("/location-references/{reference_id}", status_code=204)
def delete_location_reference(
    reference_id: int, session: Session = Depends(get_session)
) -> Response:
    structured.delete_location_reference(session, reference_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/style-profiles", response_model=list[StyleProfileRead])
def list_project_style_profiles(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return structured.list_style_profiles(session, project_id)


@router.post(
    "/projects/{project_id}/style-profiles", response_model=StyleProfileRead, status_code=201
)
def create_project_style_profile(
    project_id: int,
    payload: StyleProfileCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.create_style_profile(session, project_id, payload)


@router.get("/style-profiles/{style_profile_id}", response_model=StyleProfileRead)
def read_style_profile(
    style_profile_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    return structured.get_style_profile_payload(session, style_profile_id)


@router.patch("/style-profiles/{style_profile_id}", response_model=StyleProfileRead)
def update_style_profile(
    style_profile_id: int,
    payload: StyleProfileUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return structured.update_style_profile(session, style_profile_id, payload)


@router.delete("/style-profiles/{style_profile_id}", status_code=204)
def delete_style_profile(
    style_profile_id: int, session: Session = Depends(get_session)
) -> Response:
    structured.archive_style_profile(session, style_profile_id)
    return Response(status_code=204)


@router.patch("/shots/{shot_id}", response_model=ShotRead)
def update_shot(shot_id: int, payload: ShotUpdate, session: Session = Depends(get_session)) -> Shot:
    return studio.update_shot(session, shot_id, payload)


@router.post("/shots/{shot_id}/revisions", response_model=ShotRevisionRead)
def revise_shot(
    shot_id: int,
    payload: ShotRevisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return studio.revise_shot_spec(session, shot_id, payload)


@router.get("/shots/{shot_id}/spec", response_model=ShotSpecRead)
def read_shot_spec(shot_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    return structured.get_shot_spec_payload(session, shot_id)


@router.get("/shots/{shot_id}/spec/history", response_model=list[ShotSpecRead])
def read_shot_spec_history(
    shot_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return structured.list_shot_spec_history(session, shot_id)


@router.post("/shots/{shot_id}/spec/revisions", response_model=ShotRevisionRead)
def revise_shot_spec_structured(
    shot_id: int,
    payload: ShotSpecRevisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return studio.revise_structured_shot_spec(session, shot_id, payload)


@router.post("/shots/{shot_id}/spec/sync", response_model=ShotRevisionRead)
def sync_shot_spec(
    shot_id: int,
    payload: ShotSpecSyncRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return studio.sync_structured_shot_spec(session, shot_id, payload)


@router.post("/shots/{shot_id}/start-frame", response_model=ShotRead)
def set_start_frame(
    shot_id: int,
    payload: ShotStartFrameRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    shot = studio.set_shot_start_frame(
        session, shot_id, action=payload.action, asset_id=payload.asset_id
    )
    return studio.shot_payload(session, shot)


@router.post("/shots/{shot_id}/target-keyframe", response_model=ShotRead)
def set_target_keyframe(
    shot_id: int,
    payload: ShotTargetKeyframeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    shot = studio.set_shot_target_keyframe(session, shot_id, asset_id=payload.asset_id)
    return studio.shot_payload(session, shot)


@router.get("/shots/{shot_id}/quality-checks", response_model=list[QualityCheckResultRead])
def list_quality_checks(
    shot_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return [
        studio.quality_payload(item)
        for item in quality_service.list_shot_quality_checks(session, shot_id)
    ]


@router.post("/shots/{shot_id}/quality-checks/run", response_model=list[QualityCheckResultRead])
def run_quality_checks(
    shot_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    return [
        studio.quality_payload(item)
        for item in quality_service.run_shot_quality_checks(session, shot_id)
    ]


@router.post("/visual-continuity/reports/analyze", response_model=VisualContinuityReportRead)
def analyze_visual_continuity(
    payload: VisualContinuityAnalyzeRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if payload.analysis_version != "visual-continuity-v1":
        raise AppError(
            "VISUAL_ANALYSIS_VERSION_UNSUPPORTED",
            "The visual analysis version is unsupported.",
            409,
        )
    report = visual_continuity_service.analyze_asset(
        session,
        video_asset_id=payload.video_asset_id,
        start_anchor_asset_id=payload.start_anchor_asset_id,
        target_keyframe_asset_id=payload.target_keyframe_asset_id,
        tail_frame_asset_id=payload.tail_frame_asset_id,
    )
    return visual_continuity_service.report_payload(report)


@router.get("/visual-continuity/reports/{report_id}", response_model=VisualContinuityReportRead)
def get_visual_continuity_report(
    report_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    report = session.get(VisualContinuityReport, report_id)
    if report is None:
        raise AppError("VISUAL_REPORT_NOT_FOUND", "Visual continuity report was not found.", 404)
    return visual_continuity_service.report_payload(report)


@router.post(
    "/visual-continuity/reports/{report_id}/human-review", response_model=VisualContinuityReportRead
)
def review_visual_continuity_report(
    report_id: int,
    payload: VisualContinuityHumanReviewRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    report = visual_continuity_service.review_report(
        session,
        report_id,
        status=payload.status,
        reasons=payload.rejection_reasons,
    )
    return visual_continuity_service.report_payload(report)


@router.get("/visual-continuity/reports/{report_id}/production-gate")
def get_visual_production_gate(
    report_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    report = session.get(VisualContinuityReport, report_id)
    if report is None:
        raise AppError("VISUAL_REPORT_NOT_FOUND", "Visual continuity report was not found.", 404)
    return {
        "report_id": report.id,
        "production_gate_status": report.production_gate_status,
        "technical_status": report.technical_status,
        "automatic_visual_status": report.automatic_visual_status,
        "human_visual_status": report.human_visual_status,
    }


@router.delete("/shots/{shot_id}", status_code=204)
def delete_shot(shot_id: int, session: Session = Depends(get_session)) -> Response:
    studio.delete_shot(session, shot_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/shots/reorder", response_model=list[ShotRead])
def reorder_shots(
    project_id: int,
    payload: list[ReorderShot],
    session: Session = Depends(get_session),
) -> list[Shot]:
    return studio.reorder_shots(session, project_id, payload)


@router.post("/shots/{shot_id}/keyframe/generate", response_model=GenerationRequestRead)
def generate_keyframe(
    shot_id: int,
    background_tasks: BackgroundTasks,
    payload: GenerationStartRequest | None = None,
    session: Session = Depends(get_session),
) -> GenerationRequest:
    shot = studio.get_shot_or_404(session, shot_id)
    project = studio.get_project_or_404(session, shot.project_id)
    settings = get_settings()
    resolved = provider_resolution.resolve_generation(
        session,
        project=project,
        shot=shot,
        kind=GenerationKind.KEYFRAME,
        payload=payload,
        registry=load_registry(session),
        system_default_provider_id=settings.default_image_provider_id,
    )
    request = studio.start_keyframe_generation_atomic(
        session,
        shot=shot,
        resolved=resolved,
        request_payload=resolved.request_payload(shot),
    )
    provider_management.create_estimate_for_request(session, request)
    session.commit()
    if resolved.provider_id == provider_resolution.MOCK_PROVIDER_ID:
        background_tasks.add_task(run_request_in_background, request.id or 0)
    return request


@router.post("/shots/{shot_id}/keyframe/approve", response_model=ShotRead)
def approve_keyframe(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.approve_keyframe(session, shot_id)


@router.post("/shots/{shot_id}/keyframe/reject", response_model=ShotRead)
def reject_keyframe(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.reject_keyframe(session, shot_id)


@router.post("/shots/{shot_id}/video/generate", response_model=GenerationRequestRead)
def generate_video(
    shot_id: int,
    background_tasks: BackgroundTasks,
    payload: GenerationStartRequest | None = None,
    session: Session = Depends(get_session),
) -> GenerationRequest:
    shot = studio.get_shot_or_404(session, shot_id)
    project = studio.get_project_or_404(session, shot.project_id)
    settings = get_settings()
    resolved = provider_resolution.resolve_generation(
        session,
        project=project,
        shot=shot,
        kind=GenerationKind.VIDEO,
        payload=payload,
        registry=load_registry(session),
        system_default_provider_id=settings.default_video_provider_id,
    )
    request = studio.start_video_generation_atomic(
        session,
        shot=shot,
        resolved=resolved,
        request_payload=resolved.request_payload(shot),
    )
    provider_management.create_estimate_for_request(session, request)
    session.commit()
    if resolved.provider_id == provider_resolution.MOCK_PROVIDER_ID:
        background_tasks.add_task(run_request_in_background, request.id or 0)
    return request


@router.post("/shots/{shot_id}/video/approve", response_model=ShotRead)
def approve_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.approve_video(session, shot_id)


@router.post("/shots/{shot_id}/video/reject", response_model=ShotRead)
def reject_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.reject_video(session, shot_id)
