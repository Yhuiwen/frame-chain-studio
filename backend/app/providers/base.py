from abc import ABC, abstractmethod
from pathlib import Path

from sqlmodel import Session

from app.models.entities import GenerationRequest


class GenerationProvider(ABC):
    name: str

    @abstractmethod
    def generate_keyframe(self, session: Session, request: GenerationRequest) -> Path:
        raise NotImplementedError

    @abstractmethod
    def generate_video(self, session: Session, request: GenerationRequest) -> Path:
        raise NotImplementedError
