import shutil
import time
from pathlib import Path

from sqlmodel import Session

from app.core.config import get_settings
from app.media.ffmpeg import create_test_image, create_test_video
from app.models.entities import GenerationRequest
from app.providers.base import GenerationProvider


class MockGenerationProvider(GenerationProvider):
    name = "mock"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _fixture_image(self) -> Path:
        fixture = self.settings.fixture_dir / "mock-keyframe.png"
        if not fixture.exists():
            create_test_image(fixture)
        return fixture

    def _fixture_video(self) -> Path:
        fixture = self.settings.fixture_dir / "mock-video.mp4"
        if not fixture.exists():
            create_test_video(fixture)
        return fixture

    def generate_keyframe(self, session: Session, request: GenerationRequest) -> Path:
        del session
        time.sleep(self.settings.mock_task_delay_seconds)
        output = self.settings.storage_dir / f"project-{request.project_id}" / f"shot-{request.shot_id}"
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"keyframe-request-{request.id}.png"
        shutil.copyfile(self._fixture_image(), target)
        return target

    def generate_video(self, session: Session, request: GenerationRequest) -> Path:
        del session
        time.sleep(self.settings.mock_task_delay_seconds)
        output = self.settings.storage_dir / f"project-{request.project_id}" / f"shot-{request.shot_id}"
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"video-request-{request.id}.mp4"
        shutil.copyfile(self._fixture_video(), target)
        return target
