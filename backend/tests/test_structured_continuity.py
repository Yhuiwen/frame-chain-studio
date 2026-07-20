import json
from io import BytesIO

from PIL import Image
import pytest
from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.entities import GenerationTask, ShotCharacterRole, ShotSpec
from app.models.schemas import (
    CharacterCreate,
    CharacterReferenceCreate,
    CharacterUpdate,
    LocationCreate,
    ProjectCreate,
    ShotCharacterInput,
    ShotCreate,
    ShotSpecRevisionRequest,
    ShotSpecSyncRequest,
    StyleProfileCreate,
)
from app.services import studio, structured


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def test_structured_spec_snapshots_templates_and_generation_request_payload(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Structured"))
    shot = studio.create_shot(
        session,
        project.id or 0,
        ShotCreate(title="Gate", description="Old description", prompt="legacy shot prompt"),
    )
    character = structured.create_character(
        session,
        project.id or 0,
        CharacterCreate(name="Mira", appearance="blue jacket", default_clothing="linen scarf"),
    )
    location = structured.create_location(
        session,
        project.id or 0,
        LocationCreate(name="Harbor", description="misty dock", lighting="green sodium lamps"),
    )
    style = structured.create_style_profile(
        session,
        project.id or 0,
        StyleProfileCreate(name="Ink", positive_prompt="delicate ink", negative_prompt="muddy colors"),
    )
    reference = studio.create_project_image_asset(
        session,
        project.id or 0,
        content=png_bytes(),
        content_type="image/png",
    )
    structured.add_character_reference(
        session,
        int(character["id"]),
        CharacterReferenceCreate(asset_id=reference.id or 0, is_primary=True),
    )

    result = studio.revise_structured_shot_spec(
        session,
        shot.id or 0,
        ShotSpecRevisionRequest(
            reason="structure shot",
            changes={
                "location_id": location["id"],
                "style_profile_id": style["id"],
                "summary": "Mira reaches the fog gate",
                "action": "raises the lantern",
                "props": ["brass lantern"],
            },
            characters=[
                ShotCharacterInput(
                    character_id=int(character["id"]),
                    role=ShotCharacterRole.PRIMARY,
                    action="holds the lantern near her face",
                )
            ],
        ),
    )

    assert result["new_spec_revision"] == 2
    current = structured.get_shot_spec_payload(session, shot.id or 0)
    old = next(item for item in structured.list_shot_spec_history(session, shot.id or 0) if item["revision"] == 1)
    assert "Mira reaches the fog gate" in current["compiled_prompt"]
    assert "blue jacket" in current["compiled_prompt"]
    assert current["compiled_negative_prompt"] == "muddy colors"
    assert current["reference_asset_ids"] == [reference.id]
    assert current["structured_payload"]["shot_revision"] == 2
    assert current["structured_payload"]["style"]["positive_prompt"] == "delicate ink"
    assert current["structured_payload"]["style"]["negative_prompt"] == "muddy colors"
    assert current["structured_payload"]["location"]["name"] == "Harbor"
    assert current["structured_payload"]["characters"][0]["name"] == "Mira"
    assert current["structured_payload"]["characters"][0]["appearance"] == "blue jacket"
    assert old["compiled_prompt"] == "Shot: Old description\nContinuity: Old description\nAdditional Prompt: legacy shot prompt"

    no_op = studio.sync_structured_shot_spec(
        session,
        shot.id or 0,
        ShotSpecSyncRequest(reason="no changes", sync_location_defaults=False, sync_style_profile=False),
    )
    assert no_op["new_spec_revision"] == 2
    assert no_op["invalidated_asset_ids"] == []

    structured.update_character(
        session,
        int(character["id"]),
        CharacterUpdate(appearance="red raincoat", default_clothing="wool hood"),
    )
    unchanged = structured.get_shot_spec_payload(session, shot.id or 0)
    assert unchanged["compiled_prompt"] == current["compiled_prompt"]
    assert unchanged["structured_payload"]["characters"][0]["appearance"] == "blue jacket"

    studio.sync_structured_shot_spec(
        session,
        shot.id or 0,
        ShotSpecSyncRequest(reason="pull defaults", sync_location_defaults=False, sync_style_profile=False),
    )
    synced = structured.get_shot_spec_payload(session, shot.id or 0)
    assert synced["revision"] == 3
    assert "red raincoat" in synced["compiled_prompt"]
    assert "wool hood" in synced["compiled_prompt"]

    request = studio.start_keyframe_generation(session, shot.id or 0)
    assert request.shot_spec_revision == 3
    assert request.prompt_snapshot == synced["compiled_prompt"]
    assert request.structured_payload_json == synced["structured_payload_json"]
    assert request.compiler_version == "structured-continuity-v1"
    task = session.exec(select(GenerationTask).where(GenerationTask.generation_request_id == request.id)).one()
    task_payload = json.loads(task.request_payload_json)
    assert task_payload["prompt"] == synced["compiled_prompt"]
    assert task_payload["structured_payload"]["reference_asset_ids"] == [reference.id]
    assert task_payload["compiler_version"] == "structured-continuity-v1"


def test_structured_library_rejects_cross_project_reference_and_deletes_with_project(session: Session) -> None:
    first = studio.create_project(session, ProjectCreate(name="A"))
    second = studio.create_project(session, ProjectCreate(name="B"))
    character = structured.create_character(session, first.id or 0, CharacterCreate(name="Mira"))
    foreign_asset = studio.create_project_image_asset(
        session,
        second.id or 0,
        content=png_bytes(),
        content_type="image/png",
    )

    with pytest.raises(AppError) as exc:
        structured.add_character_reference(
            session,
            int(character["id"]),
            CharacterReferenceCreate(asset_id=foreign_asset.id or 0),
        )

    assert exc.value.code == "ASSET_NOT_FOUND"
    studio.delete_project(session, first.id or 0)
    assert session.exec(select(ShotSpec)).all() == []
