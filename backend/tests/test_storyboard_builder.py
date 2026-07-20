from app.domain.script_parser import parse_script
from app.domain.storyboard_builder import build_storyboard_draft
from app.models.entities import ScriptSourceType


def test_storyboard_builder_creates_stable_drafts_from_scenes() -> None:
    parsed = parse_script(
        "INT. LAB - NIGHT\nALICE\nI will open the door.\n\nEXT. STREET - DAY\nA car stops.\n",
        ScriptSourceType.FOUNTAIN,
    )

    first = build_storyboard_draft(parsed)
    second = build_storyboard_draft(parsed)

    assert first == second
    assert first.builder_version == "deterministic-storyboard-builder-v1"
    assert len(first.shot_drafts) == 2
    assert first.shot_drafts[0].location_name == "LAB"
    assert first.shot_drafts[0].characters[0]["character_name"] == "ALICE"
    assert first.shot_drafts[1].summary == "A car stops."
