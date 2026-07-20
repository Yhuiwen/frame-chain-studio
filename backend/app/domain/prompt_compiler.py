from dataclasses import dataclass
from typing import Any

COMPILER_VERSION = "structured-continuity-v1"
MAX_FIELD_CHARS = 1200
MAX_PROMPT_CHARS = 12000
MAX_NEGATIVE_PROMPT_CHARS = 6000


@dataclass(frozen=True)
class CharacterPromptInput:
    name: str
    role: str
    character_id: int | None = None
    sort_order: int = 0
    appearance: str = ""
    clothing: str = ""
    expression: str = ""
    action: str = ""
    position: str = ""
    props: list[str] | None = None
    continuity_notes: str = ""
    reference_asset_ids: list[int] | None = None


@dataclass(frozen=True)
class PromptCompileInput:
    shot_revision: int = 1
    shot_title: str = ""
    shot_prompt: str = ""
    shot_negative_prompt: str = ""
    style_positive_prompt: str = ""
    style_negative_prompt: str = ""
    style_rendering: str = ""
    style_camera_language: str = ""
    location_name: str = ""
    location_description: str = ""
    location_environment: str = ""
    location_architecture: str = ""
    location_time_of_day: str = ""
    location_weather: str = ""
    location_lighting: str = ""
    summary: str = ""
    action: str = ""
    emotion: str = ""
    composition: str = ""
    shot_size: str = ""
    camera_angle: str = ""
    camera_movement: str = ""
    lighting: str = ""
    time_of_day: str = ""
    weather: str = ""
    dialogue: str = ""
    continuity_notes: str = ""
    props: list[str] | None = None
    provider_overrides: dict[str, Any] | None = None
    characters: list[CharacterPromptInput] | None = None
    reference_asset_ids: list[int] | None = None


@dataclass(frozen=True)
class PromptCompileResult:
    compiled_prompt: str
    compiled_negative_prompt: str
    compiler_version: str
    structured_payload: dict[str, Any]


def compile_shot_prompt(data: PromptCompileInput) -> PromptCompileResult:
    characters = sorted(data.characters or [], key=lambda item: (item.sort_order, item.name.lower()))
    props = _clean_list(data.props)
    reference_asset_ids = _unique_ints(data.reference_asset_ids or [])
    for character in characters:
        reference_asset_ids.extend(_unique_ints(character.reference_asset_ids or []))
    reference_asset_ids = _unique_ints(reference_asset_ids)

    sections: list[str] = []
    _append(sections, "Style", _join([data.style_positive_prompt, data.style_rendering, data.style_camera_language]))
    _append(
        sections,
        "Location",
        _join(
            [
                data.location_name,
                data.location_description,
                data.location_environment,
                data.location_architecture,
                data.location_time_of_day,
                data.location_weather,
                data.location_lighting,
            ]
        ),
    )
    _append(sections, "Shot", data.summary)
    _append(sections, "Action", data.action)
    _append(sections, "Emotion", data.emotion)
    _append(sections, "Composition", _join([data.composition, data.shot_size, data.camera_angle]))
    _append(sections, "Camera Movement", data.camera_movement)
    _append(sections, "Lighting", _join([data.lighting, data.time_of_day, data.weather]))
    _append(sections, "Dialogue", data.dialogue)
    if characters:
        character_lines = [_character_line(character) for character in characters]
        _append(sections, "Characters", "; ".join(line for line in character_lines if line))
    if props:
        _append(sections, "Props", ", ".join(props))
    _append(sections, "Continuity", data.continuity_notes)
    _append(sections, "Additional Prompt", data.shot_prompt)

    negative_parts = [_clean_text(data.style_negative_prompt), _clean_text(data.shot_negative_prompt)]
    negative = ", ".join(part for part in negative_parts if part)

    payload: dict[str, Any] = {
        "compiler_version": COMPILER_VERSION,
        "shot_revision": data.shot_revision,
        "shot_title": _clean_text(data.shot_title),
        "provider_overrides": _clean_json_dict(data.provider_overrides),
        "style": {
            "positive_prompt": _clean_text(data.style_positive_prompt),
            "negative_prompt": _clean_text(data.style_negative_prompt),
            "rendering_style": _clean_text(data.style_rendering),
            "camera_language": _clean_text(data.style_camera_language),
        },
        "location": {
            "name": _clean_text(data.location_name),
            "description": _clean_text(data.location_description),
            "environment": _clean_text(data.location_environment),
            "architecture": _clean_text(data.location_architecture),
            "time_of_day": _clean_text(data.location_time_of_day),
            "weather": _clean_text(data.location_weather),
            "lighting": _clean_text(data.location_lighting),
        },
        "shot": {
            "summary": _clean_text(data.summary),
            "action": _clean_text(data.action),
            "emotion": _clean_text(data.emotion),
            "composition": _clean_text(data.composition),
            "shot_size": _clean_text(data.shot_size),
            "camera_angle": _clean_text(data.camera_angle),
            "camera_movement": _clean_text(data.camera_movement),
            "lighting": _clean_text(data.lighting),
            "time_of_day": _clean_text(data.time_of_day),
            "weather": _clean_text(data.weather),
            "dialogue": _clean_text(data.dialogue),
            "continuity_notes": _clean_text(data.continuity_notes),
            "props": props,
            "free_prompt": _clean_text(data.shot_prompt),
            "negative_prompt": _clean_text(data.shot_negative_prompt),
        },
        "characters": [_character_payload(character) for character in characters],
        "reference_asset_ids": reference_asset_ids,
    }
    return PromptCompileResult(
        compiled_prompt=_truncate("\n".join(sections), MAX_PROMPT_CHARS),
        compiled_negative_prompt=_truncate(negative, MAX_NEGATIVE_PROMPT_CHARS),
        compiler_version=COMPILER_VERSION,
        structured_payload=payload,
    )


def _append(sections: list[str], label: str, value: str) -> None:
    cleaned = _clean_text(value)
    if cleaned:
        sections.append(f"{label}: {cleaned}")


def _join(values: list[str]) -> str:
    return ", ".join(cleaned for value in values if (cleaned := _clean_text(value)))


def _character_line(character: CharacterPromptInput) -> str:
    pieces = [
        character.name,
        character.role.lower(),
        character.appearance,
        character.clothing,
        character.expression,
        character.action,
        character.position,
        ", ".join(_clean_list(character.props)),
        character.continuity_notes,
    ]
    return _join([str(piece) for piece in pieces])


def _character_payload(character: CharacterPromptInput) -> dict[str, Any]:
    return {
        "character_id": character.character_id,
        "name": _clean_text(character.name),
        "role": _clean_text(character.role),
        "sort_order": character.sort_order,
        "appearance": _clean_text(character.appearance),
        "clothing": _clean_text(character.clothing),
        "expression": _clean_text(character.expression),
        "action": _clean_text(character.action),
        "position": _clean_text(character.position),
        "props": _clean_list(character.props),
        "continuity_notes": _clean_text(character.continuity_notes),
        "reference_asset_ids": _unique_ints(character.reference_asset_ids or []),
    }


def _clean_text(value: object) -> str:
    text = str(value or "").replace("\x00", " ")
    text = " ".join(text.split())
    return _truncate(text, MAX_FIELD_CHARS)


def _clean_list(values: list[str] | None) -> list[str]:
    return [cleaned for value in values or [] if (cleaned := _clean_text(value))]


def _clean_json_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    source = value or {}
    for key in sorted(source.keys()):
        cleaned_key = _clean_text(key)
        if not cleaned_key:
            continue
        item = source[key]
        if isinstance(item, str):
            result[cleaned_key] = _clean_text(item)
        elif isinstance(item, int | float | bool) or item is None:
            result[cleaned_key] = item
        elif isinstance(item, list):
            result[cleaned_key] = [_clean_text(entry) for entry in item if _clean_text(entry)]
        else:
            result[cleaned_key] = _clean_text(item)
    return result


def _unique_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if not isinstance(value, int) or value <= 0 or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _truncate(value: str, max_chars: int) -> str:
    return value[:max_chars]
