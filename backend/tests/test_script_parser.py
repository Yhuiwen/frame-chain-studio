from app.domain.script_parser import parse_script
from app.models.entities import ScriptBlockType, ScriptSourceType


def test_parse_script_is_deterministic_and_keeps_source_ranges() -> None:
    text = "\ufeffINT. LAB - NIGHT\r\nALICE\r\nI will open the door.\r\n外景 街道 日\r\n爱丽丝：我去打开门。\r\n"
    first = parse_script(text, ScriptSourceType.FOUNTAIN)
    second = parse_script(text, ScriptSourceType.FOUNTAIN)

    assert first == second
    assert first.parser_version == "deterministic-script-parser-v1"
    assert [block.block_type for block in first.blocks] == [
        ScriptBlockType.SCENE_HEADING,
        ScriptBlockType.CHARACTER_CUE,
        ScriptBlockType.DIALOGUE,
        ScriptBlockType.SCENE_HEADING,
        ScriptBlockType.DIALOGUE,
    ]
    for block in first.blocks:
        assert text.replace("\r\n", "\n").replace("\r", "\n")[block.source_start : block.source_end] == block.source_text


def test_parse_empty_script_reports_warning() -> None:
    parsed = parse_script("", ScriptSourceType.PLAIN_TEXT)

    assert parsed.blocks == []
    assert parsed.warnings == ["empty_script"]
