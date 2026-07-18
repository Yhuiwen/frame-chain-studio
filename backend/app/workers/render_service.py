import hashlib
import os
import shutil
import subprocess
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.media.ffmpeg import require_binary
from app.media.validation import validate_video
from app.models.entities import (
    Asset,
    AssetType,
    ProjectRender,
    ProjectRenderStatus,
    ShotStatus,
    utcnow,
)
from app.services import studio, task_service

SessionFactory = Callable[[], AbstractContextManager[Session]]

ACTIVE_RENDER_STATUSES = {
    ProjectRenderStatus.QUEUED,
    ProjectRenderStatus.PREPARING,
    ProjectRenderStatus.NORMALIZING,
    ProjectRenderStatus.CONCATENATING,
    ProjectRenderStatus.VALIDATING,
    ProjectRenderStatus.FINALIZING,
}


def create_project_render(
    session: Session,
    *,
    project_id: int,
    idempotency_key: str,
    allow_partial_render: bool = False,
) -> ProjectRender:
    existing = session.exec(select(ProjectRender).where(ProjectRender.idempotency_key == idempotency_key)).first()
    if existing:
        return existing
    active = session.exec(
        select(ProjectRender).where(
            ProjectRender.project_id == project_id,
            col(ProjectRender.status).in_([status.value for status in ACTIVE_RENDER_STATUSES]),
        )
    ).first()
    if active:
        raise AppError("ACTIVE_RENDER_EXISTS", "Project already has an active render.", 409)
    project = studio.get_project_or_404(session, project_id)
    del project
    manifest = build_input_manifest(session, project_id, allow_partial_render=allow_partial_render)
    version = (
        session.exec(select(ProjectRender.render_version).where(ProjectRender.project_id == project_id).order_by(col(ProjectRender.render_version).desc())).first()
        or 0
    ) + 1
    settings = get_settings()
    render = ProjectRender(
        project_id=project_id,
        render_version=version,
        idempotency_key=idempotency_key,
        input_manifest_json=task_service.dumps_sanitized(manifest),
        settings_json=task_service.dumps_sanitized(render_settings_payload()),
        current_stage="queued",
        temporary_relative_path=f"temp/renders/project-{project_id}/render-{version}",
        final_relative_path=f"renders/project-{project_id}/render-{version}.mp4",
    )
    session.add(render)
    session.commit()
    session.refresh(render)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return render


def build_input_manifest(session: Session, project_id: int, *, allow_partial_render: bool = False) -> list[dict[str, Any]]:
    shots = studio.list_project_shots(session, project_id)
    if not shots:
        raise AppError("RENDER_INPUT_EMPTY", "Project has no shots to render.", 409)
    manifest: list[dict[str, Any]] = []
    missing: list[int] = []
    for shot in shots:
        video = studio.latest_asset(session, shot.id or 0, AssetType.VIDEO)
        if shot.status != ShotStatus.COMPLETED or video is None:
            missing.append(shot.id or 0)
            continue
        path = Path(video.path)
        if not path.exists():
            raise AppError("RENDER_INPUT_FILE_MISSING", f"Video file for Shot {shot.id} is missing.", 409)
        manifest.append(
            {
                "shot_id": shot.id,
                "sort_order": shot.sort_order,
                "video_asset_id": video.id,
                "sha256": video.sha256 or sha256_file(path),
                "duration": video.duration_seconds or shot.duration_seconds,
                "width": video.width,
                "height": video.height,
                "fps": video.fps,
            }
        )
    if missing and not allow_partial_render:
        raise AppError("RENDER_INPUT_INCOMPLETE", f"Missing approved video for shots: {missing}.", 409)
    if not manifest:
        raise AppError("RENDER_INPUT_EMPTY", "No approved videos are available for render.", 409)
    return manifest


def render_settings_payload() -> dict[str, Any]:
    settings = get_settings()
    return {
        "width": settings.render_width,
        "height": settings.render_height,
        "fps": settings.render_fps,
        "video_codec": settings.render_video_codec,
        "audio_codec": settings.render_audio_codec,
        "audio_strategy": "strip_audio",
        "pixel_format": "yuv420p",
    }


def acquire_render_lease(
    session: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> ProjectRender | None:
    current_time = task_service.db_time(now)
    render = session.exec(
        select(ProjectRender)
        .where(
            col(ProjectRender.status).in_([status.value for status in ACTIVE_RENDER_STATUSES]),
            (col(ProjectRender.locked_until).is_(None)) | (col(ProjectRender.locked_until) <= current_time),
        )
        .order_by(col(ProjectRender.created_at))
    ).first()
    if not render:
        return None
    render.locked_by = worker_id
    render.locked_until = current_time + timedelta(seconds=lease_seconds)
    render.started_at = render.started_at or current_time
    render.updated_at = current_time
    session.add(render)
    session.commit()
    session.refresh(render)
    return render


def release_render_lease(session: Session, render_id: int, *, worker_id: str) -> None:
    render = session.get(ProjectRender, render_id)
    if render and render.locked_by == worker_id:
        render.locked_by = None
        render.locked_until = None
        render.updated_at = utcnow()
        session.add(render)
        session.commit()


class RenderProcessingService:
    def __init__(self, *, session_factory: SessionFactory) -> None:
        self.session_factory = session_factory
        self.settings = get_settings()

    def process_render_once(self, render_id: int) -> bool:
        with self.session_factory() as session:
            render = session.get(ProjectRender, render_id)
            if render is None:
                return False
            manifest = task_service.loads_json_list(render.input_manifest_json)
            settings_payload = task_service.loads_json_object(render.settings_json)
            self._transition(session, render, ProjectRenderStatus.PREPARING, "preparing", 0.05)
        try:
            output_path = self._run_ffmpeg_pipeline(render_id, manifest, settings_payload)
            metadata = validate_video(output_path, timeout_seconds=self.settings.ffprobe_timeout_seconds)
            with self.session_factory() as session:
                render = session.get(ProjectRender, render_id)
                if render is None:
                    return False
                self._transition(session, render, ProjectRenderStatus.FINALIZING, "finalizing", 0.95)
                asset = self._register_asset(session, render, output_path, metadata)
                render.output_asset_id = asset.id
                render.status = ProjectRenderStatus.SUCCEEDED
                render.progress = 1
                render.current_stage = "succeeded"
                render.completed_at = utcnow()
                render.error_code = None
                render.error_message = None
                render.updated_at = utcnow()
                session.add(render)
                session.commit()
            self._cleanup_temp(render_id)
            return True
        except Exception as exc:
            with self.session_factory() as session:
                render = session.get(ProjectRender, render_id)
                if render:
                    render.status = ProjectRenderStatus.FAILED
                    render.current_stage = "failed"
                    render.error_code = getattr(exc, "code", exc.__class__.__name__)
                    render.error_message = str(exc)[:1000]
                    render.error_details_json = task_service.dumps_sanitized({"type": exc.__class__.__name__})
                    render.completed_at = utcnow()
                    render.updated_at = utcnow()
                    session.add(render)
                    session.commit()
            return True

    def _run_ffmpeg_pipeline(
        self,
        render_id: int,
        manifest: list[Any],
        settings_payload: dict[str, Any],
    ) -> Path:
        ffmpeg = require_binary("ffmpeg")
        width = int(settings_payload.get("width") or self.settings.render_width)
        height = int(settings_payload.get("height") or self.settings.render_height)
        fps = int(settings_payload.get("fps") or self.settings.render_fps)
        codec = str(settings_payload.get("video_codec") or self.settings.render_video_codec)
        temp_dir = self.settings.storage_dir / "temp" / "renders" / f"render-{render_id}"
        final_tmp = temp_dir / "render.mp4"
        final_path = self.settings.storage_dir / "renders" / f"render-{render_id}.mp4"
        temp_dir.mkdir(parents=True, exist_ok=True)
        normalized: list[Path] = []
        items = [item for item in manifest if isinstance(item, dict)]
        for index, item in enumerate(items):
            asset_id = int(item.get("video_asset_id") or 0)
            with self.session_factory() as session:
                asset = session.get(Asset, asset_id)
                if asset is None:
                    raise AppError("RENDER_INPUT_ASSET_MISSING", f"Input asset {asset_id} is missing.", 409)
                input_path = Path(asset.path)
                render = session.get(ProjectRender, render_id)
                if render:
                    self._transition(session, render, ProjectRenderStatus.NORMALIZING, f"normalizing {index + 1}/{len(items)}", 0.1 + (0.7 * index / max(len(items), 1)))
            output = temp_dir / f"segment-{index:04d}.mp4"
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,setdar={width}/{height},fps={fps},format=yuv420p"
            )
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-vf",
                vf,
                "-an",
                "-c:v",
                codec,
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ]
            _run_ffmpeg(command)
            normalized.append(output)
        with self.session_factory() as session:
            render = session.get(ProjectRender, render_id)
            if render:
                self._transition(session, render, ProjectRenderStatus.CONCATENATING, "concatenating", 0.85)
        manifest_path = temp_dir / "concat.txt"
        manifest_path.write_text("".join(f"file '{_concat_path(path)}'\n" for path in normalized), encoding="utf-8")
        _run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(manifest_path), "-c", "copy", str(final_tmp)])
        with self.session_factory() as session:
            render = session.get(ProjectRender, render_id)
            if render:
                self._transition(session, render, ProjectRenderStatus.VALIDATING, "validating", 0.9)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(final_tmp, final_path)
        return final_path

    def _register_asset(self, session: Session, render: ProjectRender, path: Path, metadata: Any) -> Asset:
        file_hash = sha256_file(path)
        existing = session.exec(
            select(Asset).where(
                Asset.project_id == render.project_id,
                Asset.type == AssetType.PROJECT_RENDER,
                Asset.sha256 == file_hash,
            )
        ).first()
        if existing:
            return existing
        asset = Asset(
            project_id=render.project_id,
            shot_id=None,
            type=AssetType.PROJECT_RENDER,
            path=str(path),
            mime_type="video/mp4",
            sha256=file_hash,
            file_size=path.stat().st_size,
            width=metadata.width,
            height=metadata.height,
            duration_seconds=metadata.duration_seconds,
            fps=metadata.fps,
            frame_count=metadata.frame_count,
            video_codec=metadata.video_codec,
            audio_codec=metadata.audio_codec,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset

    def _transition(
        self,
        session: Session,
        render: ProjectRender,
        status: ProjectRenderStatus,
        stage: str,
        progress: float,
    ) -> None:
        render.status = status
        render.current_stage = stage
        render.progress = progress
        render.updated_at = utcnow()
        session.add(render)
        session.commit()

    def _cleanup_temp(self, render_id: int) -> None:
        shutil.rmtree(self.settings.storage_dir / "temp" / "renders" / f"render-{render_id}", ignore_errors=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")


def _run_ffmpeg(command: list[str]) -> None:
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[-2000:]
        raise AppError("RENDER_FFMPEG_FAILED", stderr, 500)
