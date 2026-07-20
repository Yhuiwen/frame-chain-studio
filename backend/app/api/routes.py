from pathlib import Path
from datetime import datetime
import tempfile

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import BACKEND_ROOT, get_settings
from app.core.errors import AppError
from app.db import engine, get_session
from app.media.ffmpeg import require_binary
from app.models.entities import Asset, GenerationKind, GenerationRequest, Project, ProjectRender, Shot, TaskCommandType
from app.models.schemas import (
    GenerationStartRequest,
    GenerationRequestRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
    ReorderShot,
    ShotCreate,
    ShotRead,
    ShotRevisionRead,
    ShotRevisionRequest,
    ShotStartFrameRequest,
    ShotTargetKeyframeRequest,
    ShotUpdate,
    TaskCancelRequest,
    TaskRetryRequest,
    GenerationTaskRead,
    ProjectRenderCreate,
    ProjectRenderRead,
    WorkersStatusRead,
    QualityCheckResultRead,
)
from app.providers.config_loader import load_registry_from_env
from app.providers.exceptions import ProviderError
from app.providers.models import ProviderCapabilities, ProviderInfo
from app.providers.mock import MockGenerationProvider
from app.services import provider_resolution, quality_service, studio, task_service, worker_status
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
def list_providers() -> list[ProviderInfo]:
    try:
        return provider_resolution.list_public_providers(load_registry_from_env())
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


@router.get("/workers/status", response_model=WorkersStatusRead)
def workers_status(session: Session = Depends(get_session)) -> dict[str, object]:
    settings = get_settings()
    return worker_status.status_summary(session, stale_after_seconds=settings.worker_stale_after_seconds)


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
def list_project_renders(project_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    studio.get_project_or_404(session, project_id)
    return [studio.render_payload(render) for render in studio.list_project_renders(session, project_id)]


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
        idempotency_key=idempotency_key or f"project-render:{project_id}:{datetime.now().timestamp()}",
        allow_partial_render=payload.allow_partial_render if payload else False,
    )
    return studio.render_payload(render)


@router.get("/renders/{render_id}", response_model=ProjectRenderRead)
def read_project_render(render_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    render = session.get(ProjectRender, render_id)
    if render is None:
        raise AppError("RENDER_NOT_FOUND", f"Render {render_id} was not found.", 404)
    return studio.render_payload(render)


@router.get("/media/{asset_id}", response_model=None)
def read_asset(asset_id: int, request: Request, session: Session = Depends(get_session)) -> Response:
    return asset_response(asset_id, session=session, range_header=request.headers.get("range"))


def asset_response(asset_id: int, *, session: Session, range_header: str | None = None) -> Response:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise AppError("ASSET_NOT_FOUND", f"Asset {asset_id} was not found.", 404)
    settings = get_settings()
    storage_root = settings.storage_dir.resolve()
    asset_path = Path(asset.path).resolve()
    if storage_root not in asset_path.parents and asset_path != storage_root:
        raise AppError("ASSET_ACCESS_DENIED", "Asset file is outside the configured storage directory.", 403)
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
    project, shots, assets, requests, tasks, renders, completion, quality_checks, logs = studio.project_detail(session, project_id)
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
def update_project(project_id: int, payload: ProjectUpdate, session: Session = Depends(get_session)) -> Project:
    return studio.update_project(session, project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> Response:
    studio.delete_project(session, project_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/shots", response_model=list[ShotRead])
def list_shots(project_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [studio.shot_payload(session, shot) for shot in studio.list_project_shots(session, project_id)]


@router.post("/projects/{project_id}/shots", response_model=ShotRead, status_code=201)
def create_shot(project_id: int, payload: ShotCreate, session: Session = Depends(get_session)) -> Shot:
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


@router.post("/shots/{shot_id}/start-frame", response_model=ShotRead)
def set_start_frame(
    shot_id: int,
    payload: ShotStartFrameRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    shot = studio.set_shot_start_frame(session, shot_id, action=payload.action, asset_id=payload.asset_id)
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
def list_quality_checks(shot_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [studio.quality_payload(item) for item in quality_service.list_shot_quality_checks(session, shot_id)]


@router.post("/shots/{shot_id}/quality-checks/run", response_model=list[QualityCheckResultRead])
def run_quality_checks(shot_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [studio.quality_payload(item) for item in quality_service.run_shot_quality_checks(session, shot_id)]


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
        registry=load_registry_from_env(),
        system_default_provider_id=settings.default_image_provider_id,
    )
    request = studio.start_keyframe_generation_atomic(
        session,
        shot=shot,
        resolved=resolved,
        request_payload=resolved.request_payload(shot),
    )
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
        registry=load_registry_from_env(),
        system_default_provider_id=settings.default_video_provider_id,
    )
    request = studio.start_video_generation_atomic(
        session,
        shot=shot,
        resolved=resolved,
        request_payload=resolved.request_payload(shot),
    )
    if resolved.provider_id == provider_resolution.MOCK_PROVIDER_ID:
        background_tasks.add_task(run_request_in_background, request.id or 0)
    return request


@router.post("/shots/{shot_id}/video/approve", response_model=ShotRead)
def approve_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.approve_video(session, shot_id)


@router.post("/shots/{shot_id}/video/reject", response_model=ShotRead)
def reject_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.reject_video(session, shot_id)
