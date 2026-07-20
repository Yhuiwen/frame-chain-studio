from sqlmodel import select

from app.models.entities import Character, ScriptSourceType, ShotDraftStatus
from app.models.schemas import (
    CharacterCreate,
    LocationCreate,
    ProjectCreate,
    ScriptImportRequest,
    ShotDraftApplyRequest,
    ShotDraftUpdate,
    StoryboardCreate,
    StyleProfileCreate,
)
from app.services import script_workflow, studio, structured


def test_shot_draft_preview_and_apply_create_revision_one_spec(session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    character = structured.create_character(
        session,
        project.id or 0,
        CharacterCreate(name="Alice", appearance="silver glasses", default_clothing="white coat"),
    )
    location = structured.create_location(
        session,
        project.id or 0,
        LocationCreate(name="LAB", description="A clean laboratory", time_of_day="Night"),
    )
    style = structured.create_style_profile(
        session,
        project.id or 0,
        StyleProfileCreate(name="Ink", positive_prompt="crisp ink lines"),
    )
    imported = script_workflow.import_script(
        session,
        project.id or 0,
        ScriptImportRequest(
            title="Scene",
            text="INT. LAB - NIGHT\nALICE\nI will open the door.",
            source_type=ScriptSourceType.FOUNTAIN,
        ),
    )
    script_workflow.parse_script_document(session, imported["id"])
    storyboard = script_workflow.create_storyboard(session, imported["id"], StoryboardCreate())
    draft = script_workflow.list_shot_drafts(session, storyboard["id"])[0]
    updated = script_workflow.update_shot_draft(
        session,
        draft["id"],
        ShotDraftUpdate(
            location_id=location["id"],
            style_profile_id=style["id"],
            free_prompt="Hold on Alice before the door opens.",
            characters=[
                {
                    "character_id": character["id"],
                    "character_name": "ALICE",
                    "role": "PRIMARY",
                    "sort_order": 0,
                }
            ],
        ),
    )

    preview = script_workflow.preview_shot_draft(session, updated["id"])
    assert "silver glasses" in preview["compiled_prompt"]
    assert preview["compiler_version"] == "structured-continuity-v1"

    applied = script_workflow.apply_shot_draft(session, updated["id"], ShotDraftApplyRequest())
    repeated = script_workflow.apply_shot_draft(session, updated["id"], ShotDraftApplyRequest())

    assert applied["status"] == ShotDraftStatus.APPLIED
    assert repeated["applied_shot_id"] == applied["applied_shot_id"]
    shots = studio.list_project_shots(session, project.id or 0)
    assert len(shots) == 1
    spec = structured.get_current_shot_spec(session, shots[0])
    assert spec is not None
    assert spec.revision == 1
    assert spec.compiler_version == "structured-continuity-v1"
    assert "silver glasses" in spec.compiled_prompt


def test_unmatched_text_character_does_not_create_library_character(session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    imported = script_workflow.import_script(
        session,
        project.id or 0,
        ScriptImportRequest(title="Scene", text="ALICE: Hello.", source_type=ScriptSourceType.PLAIN_TEXT),
    )
    script_workflow.parse_script_document(session, imported["id"])
    storyboard = script_workflow.create_storyboard(session, imported["id"], StoryboardCreate())
    draft = script_workflow.list_shot_drafts(session, storyboard["id"])[0]

    script_workflow.apply_shot_draft(session, draft["id"], ShotDraftApplyRequest())

    characters = session.exec(select(Character)).all()
    assert characters == []
