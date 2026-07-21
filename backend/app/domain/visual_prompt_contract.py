from __future__ import annotations

from hashlib import sha256
import json

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError


class StableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def stable_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class CharacterLock(StableModel):
    identity_description: str
    shape: str
    proportions: str
    material: str
    colors: list[str]
    facial_features: str
    accessories: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)


class CameraLock(StableModel):
    camera_position: str
    camera_height: str
    camera_angle: str
    focal_length_style: str
    framing: str
    camera_motion_policy: str


class EnvironmentLock(StableModel):
    background: str
    surface: str
    lighting: str
    shadow_direction: str
    color_temperature: str
    forbidden_objects: list[str] = Field(default_factory=list)


class MotionDelta(StableModel):
    starting_pose: str
    ending_pose: str
    allowed_motion: str
    maximum_position_change: str
    maximum_scale_change: str
    forbidden_motion: list[str] = Field(default_factory=list)


class StyleLock(StableModel):
    rendering_style: str
    texture_style: str
    detail_level: str
    realism_level: str
    forbidden_style_shift: list[str] = Field(default_factory=list)


class VisualPromptContract(StableModel):
    character: CharacterLock
    camera: CameraLock
    environment: EnvironmentLock
    motion: MotionDelta
    style: StyleLock

    def stable_json(self) -> str:
        return json.dumps(
            self.stable_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def contract_hash(self) -> str:
        return sha256(self.stable_json().encode()).hexdigest()

    def inherit_for_next_shot(self, motion: MotionDelta) -> VisualPromptContract:
        return self.model_copy(update={"motion": motion})

    def validate_for_production(self) -> None:
        required = [
            self.character.identity_description,
            self.character.material,
            self.character.proportions,
            self.camera.camera_position,
            self.camera.focal_length_style,
            self.camera.framing,
            self.environment.background,
            self.environment.lighting,
            self.style.rendering_style,
            self.style.realism_level,
        ]
        if any(not value.strip() for value in required):
            raise AppError(
                "VISUAL_PROMPT_LOCK_INCOMPLETE", "Production visual locks are incomplete.", 409
            )

    def compile_prompt(self) -> str:
        self.validate_for_production()
        return "\n".join(
            [
                f"CHARACTER LOCK: {self.character.stable_dict()}",
                f"CAMERA LOCK: {self.camera.stable_dict()}",
                f"ENVIRONMENT LOCK: {self.environment.stable_dict()}",
                f"STYLE LOCK: {self.style.stable_dict()}",
                f"ONLY ALLOWED CHANGE — MOTION DELTA: {self.motion.stable_dict()}",
                "FORBIDDEN: style switch, camera cut, sudden subject scale change, new objects, text, logo, watermark.",
            ]
        )
