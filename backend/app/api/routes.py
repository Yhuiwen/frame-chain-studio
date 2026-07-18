from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db import engine, get_session
from app.models.entities import Asset, GenerationRequest, Project, Shot
from app.models.schemas import (
    GenerationRequestRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
    ReorderShot,
    ShotCreate,
    ShotRead,
    ShotUpdate,
)
from app.providers.mock import MockGenerationProvider
from app.services import studio

router = APIRouter()
provider = MockGenerationProvider()


def run_request_in_background(request_id: int) -> None:
    with Session(engine) as session:
        studio.run_generation_request(session, request_id, provider)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/media/{asset_id}")
def read_asset(asset_id: int, session: Session = Depends(get_session)) -> FileResponse:
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
    return FileResponse(asset_path, media_type=asset.mime_type)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return studio.list_projects(session)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    return studio.create_project(session, payload)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def project_detail(project_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    project, shots, assets, requests, logs = studio.project_detail(session, project_id)
    return {
        **ProjectRead.model_validate(project).model_dump(),
        "shots": shots,
        "assets": assets,
        "requests": requests,
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


@router.patch("/shots/{shot_id}", response_model=ShotRead)
def update_shot(shot_id: int, payload: ShotUpdate, session: Session = Depends(get_session)) -> Shot:
    return studio.update_shot(session, shot_id, payload)


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
    session: Session = Depends(get_session),
) -> GenerationRequest:
    request = studio.start_keyframe_generation(session, shot_id)
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
    session: Session = Depends(get_session),
) -> GenerationRequest:
    request = studio.start_video_generation(session, shot_id)
    background_tasks.add_task(run_request_in_background, request.id or 0)
    return request


@router.post("/shots/{shot_id}/video/approve", response_model=ShotRead)
def approve_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.approve_video(session, shot_id)


@router.post("/shots/{shot_id}/video/reject", response_model=ShotRead)
def reject_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.reject_video(session, shot_id)
