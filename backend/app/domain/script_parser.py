from dataclasses import dataclass, field
import re
from typing import Any

from app.models.entities import ScriptBlockType, ScriptSourceType


PARSER_VERSION = "deterministic-script-parser-v1"


@dataclass(frozen=True)
class ParsedBlock:
    block_type: ScriptBlockType
    sort_order: int
    source_start: int
    source_end: int
    source_text: str
    normalized_text: str
    speaker: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parse_confidence: float = 0.5
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedScript:
    blocks: list[ParsedBlock]
    warnings: list[str]
    parser_version: str
    statistics: dict[str, Any]


SCENE_PREFIXES = ("INT.", "EXT.", "INT/EXT.", "I/E.", "内景", "外景", "场景")
TRANSITION_SUFFIXES = ("TO:", "CUT TO:", "FADE OUT:", "FADE IN:", "DISSOLVE TO:")


def parse_script(raw_text: str, source_type: ScriptSourceType) -> ParsedScript:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = _lines_with_ranges(normalized)
    blocks: list[ParsedBlock] = []
    warnings: list[str] = []
    pending_speaker = ""
    order = 0
    for text, start, end in lines:
        stripped = text.strip().lstrip("\ufeff")
        if not stripped:
            pending_speaker = ""
            continue
        block_type, speaker, confidence, item_warnings = _classify_line(
            stripped,
            source_type,
            pending_speaker=pending_speaker,
        )
        if block_type == ScriptBlockType.CHARACTER_CUE:
            pending_speaker = speaker
        elif block_type == ScriptBlockType.DIALOGUE:
            speaker = speaker or pending_speaker
        else:
            pending_speaker = ""
        if item_warnings:
            warnings.extend(item_warnings)
        blocks.append(
            ParsedBlock(
                block_type=block_type,
                sort_order=order,
                source_start=start,
                source_end=end,
                source_text=normalized[start:end],
                normalized_text=stripped,
                speaker=speaker,
                parse_confidence=confidence,
                warnings=item_warnings,
            )
        )
        order += 1
    if not blocks and raw_text.strip():
        warnings.append("script_contains_text_but_no_blocks")
    if not raw_text.strip():
        warnings.append("empty_script")
    return ParsedScript(
        blocks=blocks,
        warnings=sorted(set(warnings)),
        parser_version=PARSER_VERSION,
        statistics={
            "block_count": len(blocks),
            "warning_count": len(set(warnings)),
            "source_type": source_type.value,
        },
    )


def _lines_with_ranges(text: str) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        result.append((line.rstrip("\n"), start, end))
        start = end
    if text and not text.endswith("\n") and (not result or result[-1][2] != len(text)):
        result.append((text[start:], start, len(text)))
    return result


def _classify_line(
    stripped: str,
    source_type: ScriptSourceType,
    *,
    pending_speaker: str,
) -> tuple[ScriptBlockType, str, float, list[str]]:
    warnings: list[str] = []
    if _is_comment(stripped, source_type):
        return ScriptBlockType.COMMENT, "", 0.9, warnings
    if _is_scene_heading(stripped):
        return ScriptBlockType.SCENE_HEADING, "", 0.9, warnings
    if _is_transition(stripped):
        return ScriptBlockType.TRANSITION, "", 0.85, warnings
    chinese_dialogue = re.match(r"^(?P<speaker>[\w\u4e00-\u9fff ・·]{1,24})[:：](?P<line>.+)$", stripped)
    if chinese_dialogue:
        speaker = chinese_dialogue.group("speaker").strip()
        return ScriptBlockType.DIALOGUE, speaker, 0.85, warnings
    if pending_speaker:
        block_type = ScriptBlockType.PARENTHETICAL if _is_parenthetical(stripped) else ScriptBlockType.DIALOGUE
        return block_type, pending_speaker, 0.75, warnings
    if _is_character_cue(stripped):
        return ScriptBlockType.CHARACTER_CUE, stripped.strip("@").strip(), 0.7, warnings
    if len(stripped) > 500:
        warnings.append("long_line_kept_as_action")
        return ScriptBlockType.ACTION, "", 0.45, warnings
    if source_type == ScriptSourceType.FOUNTAIN and stripped.startswith(">"):
        return ScriptBlockType.TRANSITION, "", 0.7, warnings
    if stripped in {"---", "***"}:
        return ScriptBlockType.UNKNOWN, "", 0.4, ["unrecognized_separator"]
    return ScriptBlockType.ACTION, "", 0.65, warnings


def _is_comment(text: str, source_type: ScriptSourceType) -> bool:
    return text.startswith("#") or text.startswith("//") or (
        source_type == ScriptSourceType.FOUNTAIN and text.startswith("[[") and text.endswith("]]")
    )


def _is_scene_heading(text: str) -> bool:
    upper = text.upper()
    if any(upper.startswith(prefix) for prefix in SCENE_PREFIXES):
        return True
    if re.match(r"^第[一二三四五六七八九十百\d]+[场幕]", text):
        return True
    if re.match(r"^场景[一二三四五六七八九十百\d]+[:：]", text):
        return True
    return False


def _is_transition(text: str) -> bool:
    upper = text.upper()
    return any(upper.endswith(suffix) for suffix in TRANSITION_SUFFIXES) or upper in {"CUT TO:", "FADE TO BLACK."}


def _is_character_cue(text: str) -> bool:
    if len(text) > 40 or any(char in text for char in ".!?。！？,，:："):
        return False
    if text.startswith("@") and len(text) > 1:
        return True
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and text == text.upper() and len(letters) >= 2


def _is_parenthetical(text: str) -> bool:
    return (text.startswith("(") and text.endswith(")")) or (text.startswith("（") and text.endswith("）"))
