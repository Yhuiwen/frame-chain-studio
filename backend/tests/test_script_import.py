import pytest

from app.core.errors import AppError
from app.models.entities import ScriptDocumentStatus, ScriptSourceType
from app.models.schemas import ProjectCreate, ScriptImportRequest
from app.services import script_workflow, studio


def test_import_script_detects_duplicate_sha_without_overwriting(session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    payload = ScriptImportRequest(title="Scene", text="INT. LAB - NIGHT\nAction.", source_type=ScriptSourceType.PLAIN_TEXT)

    first = script_workflow.import_script(session, project.id or 0, payload)
    duplicate = script_workflow.import_script(session, project.id or 0, payload)

    assert duplicate["id"] == first["id"]
    assert duplicate["duplicate_of_id"] == first["id"]
    assert duplicate["version"] == 1


def test_import_script_allows_explicit_new_version(session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    payload = ScriptImportRequest(title="Scene", text="INT. LAB - NIGHT\nAction.", source_type=ScriptSourceType.PLAIN_TEXT)
    first = script_workflow.import_script(session, project.id or 0, payload)

    second = script_workflow.import_script(
        session,
        project.id or 0,
        ScriptImportRequest(
            title="Scene v2",
            text="INT. LAB - NIGHT\nAction.",
            source_type=ScriptSourceType.PLAIN_TEXT,
            create_new_version=True,
            parent_document_id=first["id"],
        ),
    )

    assert second["id"] != first["id"]
    assert second["version"] == 2
    assert second["parent_document_id"] == first["id"]


def test_parse_replaces_current_blocks_deterministically(session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    imported = script_workflow.import_script(
        session,
        project.id or 0,
        ScriptImportRequest(title="Scene", text="INT. LAB - NIGHT\nAction.", source_type=ScriptSourceType.FOUNTAIN),
    )

    first = script_workflow.parse_script_document(session, imported["id"])
    second = script_workflow.parse_script_document(session, imported["id"])

    assert first["block_count"] == second["block_count"] == 2
    current = script_workflow.get_script_or_404(session, imported["id"])
    assert current.status == ScriptDocumentStatus.PARSED
    assert current.parse_revision == 2
    assert len(script_workflow.list_blocks(session, imported["id"])) == 2


def test_decode_rejects_non_utf8_text() -> None:
    with pytest.raises(AppError) as exc:
        script_workflow.decode_script_upload(b"\xff", filename="bad.txt", mime_type="text/plain")
    assert exc.value.code == "SCRIPT_DECODE_ERROR"
