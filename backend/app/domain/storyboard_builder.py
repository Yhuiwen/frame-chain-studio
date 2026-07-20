from dataclasses import dataclass, field
from typing import Any

from app.domain.script_parser import ParsedBlock, ParsedScript
from app.models.entities import ScriptBlockType


BUILDER_VERSION = "deterministic-storyboard-builder-v1"


@dataclass(frozen=True)
class StoryboardBuildOptions:
    max_shot_drafts: int = 500
    max_blocks_per_draft: int = 8


@dataclass(frozen=True)
class ShotDraftPlan:
    source_block_start_order: int
    source_block_end_order: int
    title: str
    summary: str
    action: str
    dialogue: str
    suggested_duration_seconds: float
    location_name: str = ""
    time_of_day: str = ""
    weather: str = ""
    characters: list[dict[str, Any]] = field(default_factory=list)
    continuity_notes: str = ""


@dataclass(frozen=True)
class StoryboardDraftPlan:
    parser_version: str
    builder_version: str
    shot_drafts: list[ShotDraftPlan]
    warnings: list[str]
    statistics: dict[str, Any]


def build_storyboard_draft(
    parsed_script: ParsedScript,
    options: StoryboardBuildOptions | None = None,
) -> StoryboardDraftPlan:
    opts = options or StoryboardBuildOptions()
    warnings: list[str] = []
    chunks = _scene_chunks(parsed_script.blocks)
    drafts: list[ShotDraftPlan] = []
    for chunk in chunks:
        for split in _split_chunk(chunk, max_blocks=opts.max_blocks_per_draft):
            if len(drafts) >= opts.max_shot_drafts:
                warnings.append("max_shot_drafts_reached")
                break
            drafts.append(_draft_from_blocks(split, index=len(drafts)))
        if len(drafts) >= opts.max_shot_drafts:
            break
    if not drafts and parsed_script.blocks:
        drafts.append(_draft_from_blocks(parsed_script.blocks, index=0))
    return StoryboardDraftPlan(
        parser_version=parsed_script.parser_version,
        builder_version=BUILDER_VERSION,
        shot_drafts=drafts,
        warnings=sorted(set(warnings)),
        statistics={"shot_draft_count": len(drafts), "source_block_count": len(parsed_script.blocks)},
    )


def _scene_chunks(blocks: list[ParsedBlock]) -> list[list[ParsedBlock]]:
    chunks: list[list[ParsedBlock]] = []
    current: list[ParsedBlock] = []
    for block in blocks:
        if block.block_type == ScriptBlockType.SCENE_HEADING and current:
            chunks.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        chunks.append(current)
    return chunks


def _split_chunk(blocks: list[ParsedBlock], *, max_blocks: int) -> list[list[ParsedBlock]]:
    if len(blocks) <= max_blocks:
        return [blocks]
    result: list[list[ParsedBlock]] = []
    current: list[ParsedBlock] = []
    for block in blocks:
        if current and len(current) >= max_blocks and block.block_type in {ScriptBlockType.ACTION, ScriptBlockType.SCENE_HEADING}:
            result.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        result.append(current)
    return result


def _draft_from_blocks(blocks: list[ParsedBlock], *, index: int) -> ShotDraftPlan:
    scene = next((block for block in blocks if block.block_type == ScriptBlockType.SCENE_HEADING), None)
    actions = [block.normalized_text for block in blocks if block.block_type in {ScriptBlockType.ACTION, ScriptBlockType.UNKNOWN}]
    dialogues = [block.normalized_text for block in blocks if block.block_type == ScriptBlockType.DIALOGUE]
    speakers = _unique([block.speaker for block in blocks if block.speaker])
    title = scene.normalized_text if scene else f"Draft Shot {index + 1}"
    summary_source = actions[0] if actions else (dialogues[0] if dialogues else title)
    duration = min(12.0, max(2.0, round((len(" ".join(actions + dialogues)) / 80) + 3, 1)))
    return ShotDraftPlan(
        source_block_start_order=blocks[0].sort_order,
        source_block_end_order=blocks[-1].sort_order,
        title=title[:160],
        summary=summary_source[:4000],
        action="\n".join(actions)[:4000],
        dialogue="\n".join(dialogues)[:4000],
        suggested_duration_seconds=duration,
        location_name=_location_from_scene(title),
        time_of_day=_time_from_scene(title),
        characters=[
            {"character_name": speaker, "role": "PRIMARY" if order == 0 else "SECONDARY", "sort_order": order}
            for order, speaker in enumerate(speakers)
        ],
        continuity_notes="Generated from script blocks; review before applying.",
    )


def _location_from_scene(scene: str) -> str:
    cleaned = scene.replace("INT.", "").replace("EXT.", "").replace("内景", "").replace("外景", "").strip()
    if " - " in cleaned:
        return cleaned.split(" - ", 1)[0].strip()
    if "：" in cleaned:
        return cleaned.split("：", 1)[-1].strip()
    if ":" in cleaned:
        return cleaned.split(":", 1)[-1].strip()
    return cleaned[:160]


def _time_from_scene(scene: str) -> str:
    upper = scene.upper()
    for token in ("NIGHT", "DAY", "MORNING", "EVENING"):
        if token in upper:
            return token.title()
    if "夜" in scene:
        return "夜"
    if "日" in scene or "白天" in scene:
        return "日"
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = " ".join(value.split()).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
