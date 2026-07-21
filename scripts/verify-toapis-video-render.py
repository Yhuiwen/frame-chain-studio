from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.media.validation import validate_video  # noqa: E402
from app.models.entities import Asset, AssetStatus, AssetType, Project, ProjectRender, ProjectRenderStatus, Shot, ShotStatus  # noqa: E402
from app.workers.render_service import RenderProcessingService, create_project_render, sha256_file  # noqa: E402
from app.workers.render_worker import RenderWorker  # noqa: E402


async def main() -> int:
    with sqlite3.connect(ROOT / "backend" / "data" / "frame_chain.db") as connection:
        source = Path(connection.execute("SELECT path FROM asset WHERE id=80").fetchone()[0])
    with tempfile.TemporaryDirectory(prefix="fcs-video-render-") as temp:
        temp_root = Path(temp)
        settings = get_settings()
        previous_storage = settings.storage_dir
        settings.storage_dir = temp_root / "storage"
        settings.storage_dir.mkdir(parents=True)
        copied = settings.storage_dir / "canary-input.mp4"
        shutil.copyfile(source, copied)
        engine = create_engine(f"sqlite:///{temp_root / 'render.db'}")
        SQLModel.metadata.create_all(engine)

        @contextmanager
        def factory():
            with Session(engine) as session:
                yield session

        try:
            with Session(engine) as session:
                project = Project(name="TOAPIS real-video compatibility")
                session.add(project); session.commit(); session.refresh(project)
                shot = Shot(project_id=project.id or 0, title="Canary", status=ShotStatus.COMPLETED)
                session.add(shot); session.commit(); session.refresh(shot)
                asset = Asset(
                    project_id=project.id or 0, shot_id=shot.id, type=AssetType.VIDEO,
                    status=AssetStatus.APPROVED, revision=shot.spec_revision, path=str(copied),
                    mime_type="video/mp4", duration_seconds=1.041667, width=1280, height=720,
                    fps=24, sha256=sha256_file(copied),
                )
                session.add(asset); session.commit(); session.refresh(asset)
                shot.approved_video_asset_id = asset.id; session.add(shot); session.commit()
                render = create_project_render(session, project_id=project.id or 0, idempotency_key="real-canary-render")
            worker = RenderWorker(
                session_factory=factory, worker_id="real-video-render-check", lease_seconds=30,
                processing_service=RenderProcessingService(session_factory=factory),
            )
            if await worker.run_until_idle() != 1:
                raise RuntimeError("RENDER_WORKER_DID_NOT_PROCESS")
            with Session(engine) as session:
                saved = session.get(ProjectRender, render.id)
                if not saved or saved.status != ProjectRenderStatus.SUCCEEDED or not saved.output_asset_id:
                    raise RuntimeError("REAL_VIDEO_RENDER_FAILED")
                output = session.get(Asset, saved.output_asset_id)
                metadata = validate_video(Path(output.path), timeout_seconds=30) if output else None
                if not metadata or metadata.width <= 0 or metadata.height <= 0:
                    raise RuntimeError("REAL_VIDEO_RENDER_INVALID")
                print(f"renderStatus=SUCCEEDED width={metadata.width} height={metadata.height} duration={metadata.duration_seconds}")
        finally:
            engine.dispose()
            settings.storage_dir = previous_storage
    print("temporaryArtifactsCleaned=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
