import hashlib
import json
from pathlib import Path
from typing import Any
import zipfile
from xml.etree import ElementTree

from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.domain.script_parser import parse_script
from app.domain.storyboard_builder import StoryboardBuildOptions, build_storyboard_draft
from app.models.entities import (
    Character,
    GenerationTask,
    Location,
    ProjectRender,
    ReliableTaskStatus,
    ScriptBlock,
    ScriptDocument,
    ScriptDocumentStatus,
    ScriptSourceType,
    Shot,
    ShotCharacter,
    ShotCharacterRole,
    ShotDraft,
    ShotDraftCharacter,
    ShotDraftStatus,
    ShotSpec,
    StoryboardDraft,
    StoryboardDraftStatus,
    StyleProfile,
    utcnow,
)
from app.models.schemas import (
    ScriptBlockUpdate,
    ScriptImportRequest,
    ShotDraftApplyRequest,
    ShotDraftCharacterInput,
    ShotDraftSplitRequest,
    ShotDraftUpdate,
    ShotCharacterInput,
    StoryboardApplyRequest,
    StoryboardCreate,
    StoryboardUpdate,
)
from app.services import structured
from app.domain.prompt_compiler import CharacterPromptInput
from app.services.studio import create_shot, get_project_or_404
from app.models.schemas import ShotCreate


TEXT_EXTENSIONS = {".txt": ScriptSourceType.PLAIN_TEXT, ".md": ScriptSourceType.MARKDOWN, ".fountain": ScriptSourceType.FOUNTAIN}
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def decode_script_upload(
    content: bytes,
    *,
    filename: str,
    mime_type: str,
) -> tuple[str, ScriptSourceType]:
    settings = get_settings()
    if len(content) > settings.script_max_file_bytes:
        raise AppError("SCRIPT_FILE_TOO_LARGE", "Script file is larger than the configured limit.", 413)
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".docx" or mime_type == DOCX_CONTENT_TYPE:
        return _extract_docx_text(content), ScriptSourceType.DOCX
    if suffix not in TEXT_EXTENSIONS:
        raise AppError("UNSUPPORTED_SCRIPT_TYPE", "Supported script formats are .txt, .md, .fountain, and .docx.", 400)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("SCRIPT_DECODE_ERROR", "Script text must be valid UTF-8.", 400) from exc
    return _bounded_text(text), TEXT_EXTENSIONS[suffix]


def import_script(
    session: Session,
    project_id: int,
    payload: ScriptImportRequest,
    *,
    raw_text: str | None = None,
    source_type: ScriptSourceType | None = None,
    original_filename: str = "",
    mime_type: str = "",
) -> dict[str, Any]:
    get_project_or_404(session, project_id)
    text = _bounded_text(raw_text if raw_text is not None else payload.text or "")
    if not text.strip():
        raise AppError("SCRIPT_EMPTY", "Script text is empty.", 400)
    resolved_source_type = source_type or payload.source_type
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = session.exec(
        select(ScriptDocument)
        .where(ScriptDocument.project_id == project_id, ScriptDocument.content_sha256 == sha)
        .order_by(col(ScriptDocument.version))
    ).first()
    if existing is not None and not payload.create_new_version:
        return {**script_document_payload(session, existing), "duplicate_of_id": existing.id}
    parent = session.get(ScriptDocument, payload.parent_document_id) if payload.parent_document_id else existing
    if parent is not None and parent.project_id != project_id:
        raise AppError("CROSS_PROJECT_SCRIPT_VERSION", "Parent script belongs to another project.", 409)
    max_version = session.exec(
        select(ScriptDocument.version)
        .where(ScriptDocument.project_id == project_id, ScriptDocument.content_sha256 == sha)
        .order_by(col(ScriptDocument.version).desc())
    ).first()
    document = ScriptDocument(
        project_id=project_id,
        title=(payload.title or _title_from_filename(original_filename) or "Imported Script")[:160],
        source_type=resolved_source_type,
        original_filename=Path(original_filename).name[:260] if original_filename else "",
        mime_type=mime_type[:160],
        content_sha256=sha,
        raw_text=text,
        language=payload.language,
        version=(max_version + 1) if max_version is not None else 1,
        parent_document_id=parent.id if parent else None,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return script_document_payload(session, document)


def list_scripts(session: Session, project_id: int) -> list[dict[str, Any]]:
    get_project_or_404(session, project_id)
    docs = session.exec(
        select(ScriptDocument).where(ScriptDocument.project_id == project_id).order_by(col(ScriptDocument.created_at))
    ).all()
    return [script_document_payload(session, item) for item in docs]


def get_script_or_404(session: Session, script_id: int) -> ScriptDocument:
    script = session.get(ScriptDocument, script_id)
    if script is None:
        raise AppError("SCRIPT_NOT_FOUND", f"Script {script_id} was not found.", 404)
    return script


def parse_script_document(session: Session, script_id: int) -> dict[str, Any]:
    script = get_script_or_404(session, script_id)
    settings = get_settings()
    parsed = parse_script(script.raw_text, script.source_type)
    if len(parsed.blocks) > settings.script_max_blocks:
        raise AppError("SCRIPT_TOO_MANY_BLOCKS", "Parsed script has more blocks than allowed.", 413)
    revision = script.parse_revision + 1
    for old in session.exec(select(ScriptBlock).where(ScriptBlock.script_document_id == script.id)).all():
        session.delete(old)
    session.flush()
    for block in parsed.blocks:
        session.add(
            ScriptBlock(
                script_document_id=script.id or 0,
                parse_revision=revision,
                block_type=block.block_type,
                sort_order=block.sort_order,
                source_start=block.source_start,
                source_end=block.source_end,
                source_text=block.source_text,
                normalized_text=block.normalized_text,
                speaker=block.speaker,
                metadata_json=dumps(block.metadata),
                parse_confidence=block.parse_confidence,
                parse_warnings_json=dumps(block.warnings),
            )
        )
    script.parse_revision = revision
    script.status = ScriptDocumentStatus.PARSE_WARNING if parsed.warnings else ScriptDocumentStatus.PARSED
    script.updated_at = utcnow()
    session.add(script)
    session.commit()
    session.refresh(script)
    return {
        "script": script_document_payload(session, script),
        "parser_version": parsed.parser_version,
        "block_count": len(parsed.blocks),
        "warnings": parsed.warnings,
        "statistics": parsed.statistics,
    }


def list_blocks(session: Session, script_id: int) -> list[dict[str, Any]]:
    script = get_script_or_404(session, script_id)
    blocks = session.exec(
        select(ScriptBlock)
        .where(ScriptBlock.script_document_id == script.id, ScriptBlock.parse_revision == script.parse_revision)
        .order_by(col(ScriptBlock.sort_order), col(ScriptBlock.id))
    ).all()
    return [script_block_payload(item) for item in blocks]


def update_block(session: Session, block_id: int, payload: ScriptBlockUpdate) -> dict[str, Any]:
    block = session.get(ScriptBlock, block_id)
    if block is None:
        raise AppError("SCRIPT_BLOCK_NOT_FOUND", f"Script block {block_id} was not found.", 404)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(block, key, value)
    session.add(block)
    session.commit()
    session.refresh(block)
    return script_block_payload(block)


def create_storyboard(session: Session, script_id: int, payload: StoryboardCreate) -> dict[str, Any]:
    script = get_script_or_404(session, script_id)
    if script.parse_revision <= 0:
        parse_script_document(session, script_id)
        script = get_script_or_404(session, script_id)
    if payload.default_style_profile_id is not None:
        style = session.get(StyleProfile, payload.default_style_profile_id)
        if style is None or style.project_id != script.project_id:
            raise AppError("STYLE_PROFILE_NOT_FOUND", "StyleProfile was not found in this project.", 404)
    parsed = parse_script(script.raw_text, script.source_type)
    block_by_order = {
        block.sort_order: block
        for block in session.exec(
            select(ScriptBlock)
            .where(ScriptBlock.script_document_id == script.id, ScriptBlock.parse_revision == script.parse_revision)
            .order_by(col(ScriptBlock.sort_order))
        ).all()
    }
    plan = build_storyboard_draft(
        parsed,
        StoryboardBuildOptions(max_shot_drafts=get_settings().script_max_shot_drafts),
    )
    storyboard = StoryboardDraft(
        project_id=script.project_id,
        script_document_id=script.id or 0,
        name=payload.name or f"{script.title} Storyboard",
        parser_version=plan.parser_version,
        builder_version=plan.builder_version,
        default_style_profile_id=payload.default_style_profile_id,
    )
    session.add(storyboard)
    session.flush()
    for index, draft_plan in enumerate(plan.shot_drafts):
        start_block = block_by_order.get(draft_plan.source_block_start_order)
        end_block = block_by_order.get(draft_plan.source_block_end_order)
        draft = ShotDraft(
            storyboard_draft_id=storyboard.id or 0,
            sort_order=index,
            source_block_start_id=start_block.id if start_block else None,
            source_block_end_id=end_block.id if end_block else None,
            title=draft_plan.title,
            summary=draft_plan.summary,
            action=draft_plan.action,
            dialogue=draft_plan.dialogue,
            suggested_duration_seconds=draft_plan.suggested_duration_seconds,
            location_name=draft_plan.location_name,
            time_of_day=draft_plan.time_of_day,
            continuity_notes=draft_plan.continuity_notes,
            style_profile_id=payload.default_style_profile_id,
        )
        session.add(draft)
        session.flush()
        for character in draft_plan.characters:
            session.add(
                ShotDraftCharacter(
                    shot_draft_id=draft.id or 0,
                    character_name=str(character.get("character_name") or ""),
                    role=ShotCharacterRole(str(character.get("role") or ShotCharacterRole.SECONDARY.value)),
                    sort_order=int(character.get("sort_order") or 0),
                )
            )
    session.commit()
    session.refresh(storyboard)
    return storyboard_payload(session, storyboard)


def list_storyboards(session: Session, script_id: int) -> list[dict[str, Any]]:
    script = get_script_or_404(session, script_id)
    boards = session.exec(
        select(StoryboardDraft)
        .where(StoryboardDraft.script_document_id == script.id)
        .order_by(col(StoryboardDraft.created_at), col(StoryboardDraft.id))
    ).all()
    return [storyboard_payload(session, item) for item in boards]


def get_storyboard_or_404(session: Session, storyboard_id: int) -> StoryboardDraft:
    storyboard = session.get(StoryboardDraft, storyboard_id)
    if storyboard is None:
        raise AppError("STORYBOARD_NOT_FOUND", f"Storyboard {storyboard_id} was not found.", 404)
    return storyboard


def update_storyboard(session: Session, storyboard_id: int, payload: StoryboardUpdate) -> dict[str, Any]:
    storyboard = get_storyboard_or_404(session, storyboard_id)
    updates = payload.model_dump(exclude_unset=True)
    if "default_style_profile_id" in updates and updates["default_style_profile_id"] is not None:
        style = session.get(StyleProfile, updates["default_style_profile_id"])
        if style is None or style.project_id != storyboard.project_id:
            raise AppError("STYLE_PROFILE_NOT_FOUND", "StyleProfile was not found in this project.", 404)
    for key, value in updates.items():
        setattr(storyboard, key, value)
    storyboard.updated_at = utcnow()
    session.add(storyboard)
    session.commit()
    session.refresh(storyboard)
    return storyboard_payload(session, storyboard)


def list_shot_drafts(session: Session, storyboard_id: int) -> list[dict[str, Any]]:
    storyboard = get_storyboard_or_404(session, storyboard_id)
    drafts = session.exec(
        select(ShotDraft).where(ShotDraft.storyboard_draft_id == storyboard.id).order_by(col(ShotDraft.sort_order), col(ShotDraft.id))
    ).all()
    return [shot_draft_payload(session, item) for item in drafts]


def get_shot_draft_or_404(session: Session, shot_draft_id: int) -> ShotDraft:
    draft = session.get(ShotDraft, shot_draft_id)
    if draft is None:
        raise AppError("SHOT_DRAFT_NOT_FOUND", f"ShotDraft {shot_draft_id} was not found.", 404)
    return draft


def update_shot_draft(session: Session, shot_draft_id: int, payload: ShotDraftUpdate) -> dict[str, Any]:
    draft = get_shot_draft_or_404(session, shot_draft_id)
    _ensure_draft_editable(draft)
    updates = payload.model_dump(exclude_unset=True)
    if "location_id" in updates and updates["location_id"] is not None:
        _validate_location(session, draft, updates["location_id"])
    if "style_profile_id" in updates and updates["style_profile_id"] is not None:
        _validate_style(session, draft, updates["style_profile_id"])
    raw_characters = updates.pop("characters", None)
    characters = (
        [item if isinstance(item, ShotDraftCharacterInput) else ShotDraftCharacterInput.model_validate(item) for item in raw_characters]
        if raw_characters is not None
        else None
    )
    for key, value in updates.items():
        if key == "props":
            draft.props_json = dumps(value or [])
        else:
            setattr(draft, key, value)
    if characters is not None:
        _replace_draft_characters(session, draft, characters)
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return shot_draft_payload(session, draft)


def split_shot_draft(session: Session, shot_draft_id: int, payload: ShotDraftSplitRequest) -> list[dict[str, Any]]:
    draft = get_shot_draft_or_404(session, shot_draft_id)
    _ensure_draft_editable(draft)
    if payload.split_after_block_id is None:
        raise AppError("SPLIT_POINT_REQUIRED", "A source block split point is required.", 400)
    split_block = session.get(ScriptBlock, payload.split_after_block_id)
    if split_block is None:
        raise AppError("SCRIPT_BLOCK_NOT_FOUND", "Split block was not found.", 404)
    start_id = draft.source_block_start_id or split_block.id or 0
    end_id = draft.source_block_end_id or split_block.id or 0
    source_ids = _block_ids_in_range(session, start_id, end_id)
    if split_block.id not in source_ids or split_block.id == end_id:
        raise AppError("INVALID_SPLIT_POINT", "Split point must be inside the draft source range.", 400)
    after_ids = source_ids[source_ids.index(split_block.id) + 1 :]
    next_order = draft.sort_order + 1
    _shift_draft_orders(session, draft.storyboard_draft_id, next_order)
    new_draft = ShotDraft(
        storyboard_draft_id=draft.storyboard_draft_id,
        sort_order=next_order,
        source_block_start_id=after_ids[0],
        source_block_end_id=end_id,
        title=f"{draft.title} B"[:160],
        summary=draft.summary,
        action=draft.action,
        dialogue=draft.dialogue,
        suggested_duration_seconds=draft.suggested_duration_seconds,
        location_id=draft.location_id,
        location_name=draft.location_name,
        style_profile_id=draft.style_profile_id,
        time_of_day=draft.time_of_day,
        weather=draft.weather,
        shot_size=draft.shot_size,
        camera_angle=draft.camera_angle,
        camera_movement=draft.camera_movement,
        composition=draft.composition,
        lighting=draft.lighting,
        emotion=draft.emotion,
        props_json=draft.props_json,
        continuity_notes=draft.continuity_notes,
        free_prompt=draft.free_prompt,
        negative_prompt=draft.negative_prompt,
    )
    draft.source_block_end_id = split_block.id
    draft.title = f"{draft.title} A"[:160]
    draft.updated_at = utcnow()
    session.add(draft)
    session.add(new_draft)
    session.commit()
    return [shot_draft_payload(session, draft), shot_draft_payload(session, new_draft)]


def merge_shot_draft_next(session: Session, shot_draft_id: int) -> dict[str, Any]:
    draft = get_shot_draft_or_404(session, shot_draft_id)
    _ensure_draft_editable(draft)
    next_draft = session.exec(
        select(ShotDraft)
        .where(ShotDraft.storyboard_draft_id == draft.storyboard_draft_id, ShotDraft.sort_order > draft.sort_order)
        .order_by(col(ShotDraft.sort_order), col(ShotDraft.id))
    ).first()
    if next_draft is None or next_draft.status in {ShotDraftStatus.APPLIED, ShotDraftStatus.SKIPPED}:
        raise AppError("SHOT_DRAFT_MERGE_UNAVAILABLE", "The next draft cannot be merged.", 409)
    draft.source_block_end_id = next_draft.source_block_end_id or draft.source_block_end_id
    draft.summary = _join_text(draft.summary, next_draft.summary, max_len=4000)
    draft.action = _join_text(draft.action, next_draft.action, max_len=4000)
    draft.dialogue = _join_text(draft.dialogue, next_draft.dialogue, max_len=4000)
    draft.props_json = dumps(_unique(loads_list(draft.props_json) + loads_list(next_draft.props_json)))
    draft.updated_at = utcnow()
    session.delete(next_draft)
    for item in session.exec(
        select(ShotDraft).where(ShotDraft.storyboard_draft_id == draft.storyboard_draft_id, ShotDraft.sort_order > next_draft.sort_order)
    ).all():
        item.sort_order -= 1
        session.add(item)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return shot_draft_payload(session, draft)


def set_shot_draft_status(session: Session, shot_draft_id: int, status: ShotDraftStatus) -> dict[str, Any]:
    draft = get_shot_draft_or_404(session, shot_draft_id)
    if draft.status == ShotDraftStatus.APPLIED:
        raise AppError("SHOT_DRAFT_ALREADY_APPLIED", "Applied drafts cannot be changed.", 409)
    draft.status = status
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return shot_draft_payload(session, draft)


def preview_shot_draft(session: Session, shot_draft_id: int) -> dict[str, Any]:
    draft = get_shot_draft_or_404(session, shot_draft_id)
    shot = Shot(
        id=0,
        project_id=_storyboard_project_id(session, draft),
        title=draft.title or "Draft Shot",
        description=draft.summary,
        duration_seconds=draft.suggested_duration_seconds,
        prompt=draft.free_prompt,
        negative_prompt=draft.negative_prompt,
        spec_revision=1,
    )
    spec = _draft_spec(draft, shot_id=0)
    result = structured.compile_shot_prompt(
        structured.build_compile_input(session, shot, spec, character_inputs=_draft_prompt_characters(session, draft))
    )
    payload = {
        "id": None,
        "shot_id": None,
        "revision": 1,
        "location_id": draft.location_id,
        "style_profile_id": draft.style_profile_id,
        "summary": draft.summary,
        "action": draft.action,
        "dialogue": draft.dialogue,
    }
    return {
        "shot_spec": payload,
        "compiled_prompt": result.compiled_prompt,
        "compiled_negative_prompt": result.compiled_negative_prompt,
        "structured_payload": result.structured_payload,
        "compiler_version": result.compiler_version,
        "reference_asset_ids": [item for item in result.structured_payload.get("reference_asset_ids", []) if isinstance(item, int)],
        "validation_warnings": [],
    }


def apply_shot_draft(session: Session, shot_draft_id: int, payload: ShotDraftApplyRequest) -> dict[str, Any]:
    draft = get_shot_draft_or_404(session, shot_draft_id)
    if draft.applied_shot_id:
        shot = session.get(Shot, draft.applied_shot_id)
        if shot is None:
            raise AppError("APPLIED_SHOT_MISSING", "Applied shot is missing.", 409)
        return shot_draft_payload(session, draft)
    _ensure_can_apply(session, _storyboard_project_id(session, draft))
    if draft.status == ShotDraftStatus.SKIPPED:
        raise AppError("SHOT_DRAFT_SKIPPED", "Skipped drafts cannot be applied.", 409)
    project_id = _storyboard_project_id(session, draft)
    shot = create_shot(
        session,
        project_id,
        ShotCreate(
            title=draft.title or "Draft Shot",
            description=draft.summary,
            duration_seconds=draft.suggested_duration_seconds,
            prompt=draft.free_prompt,
            negative_prompt=draft.negative_prompt,
        ),
    )
    if payload.insert_after_shot_id is not None:
        _move_shot_after(session, shot, payload.insert_after_shot_id)
    spec = structured.get_current_shot_spec(session, shot)
    if spec is None:
        raise AppError("SHOT_SPEC_MISSING", "Initial ShotSpec was not created.", 500)
    _apply_draft_to_spec(session, draft, shot, spec)
    draft.applied_shot_id = shot.id
    draft.status = ShotDraftStatus.APPLIED
    draft.updated_at = utcnow()
    session.add(draft)
    _refresh_storyboard_status(session, draft.storyboard_draft_id)
    session.commit()
    session.refresh(draft)
    return shot_draft_payload(session, draft)


def apply_storyboard(session: Session, storyboard_id: int, payload: StoryboardApplyRequest) -> dict[str, Any]:
    storyboard = get_storyboard_or_404(session, storyboard_id)
    _ensure_can_apply(session, storyboard.project_id)
    draft_ids = payload.shot_draft_ids
    if not draft_ids:
        raise AppError("SHOT_DRAFT_SELECTION_REQUIRED", "Select at least one ShotDraft to apply.", 400)
    drafts = session.exec(select(ShotDraft).where(col(ShotDraft.id).in_(draft_ids))).all()
    if len(drafts) != len(set(draft_ids)):
        raise AppError("SHOT_DRAFT_NOT_FOUND", "One or more selected drafts were not found.", 404)
    ordered = sorted(drafts, key=lambda item: item.sort_order)
    applied: list[int] = []
    insert_after = payload.insert_after_shot_id
    try:
        for draft in ordered:
            result = apply_shot_draft(session, draft.id or 0, ShotDraftApplyRequest(insert_after_shot_id=insert_after))
            applied_shot_id = result.get("applied_shot_id")
            if isinstance(applied_shot_id, int):
                applied.append(applied_shot_id)
                insert_after = applied_shot_id
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"storyboard": storyboard_payload(session, storyboard), "applied_shot_ids": applied}


def archive_script(session: Session, script_id: int) -> dict[str, Any]:
    script = get_script_or_404(session, script_id)
    script.status = ScriptDocumentStatus.ARCHIVED
    script.updated_at = utcnow()
    session.add(script)
    session.commit()
    session.refresh(script)
    return script_document_payload(session, script)


def archive_storyboard(session: Session, storyboard_id: int) -> dict[str, Any]:
    storyboard = get_storyboard_or_404(session, storyboard_id)
    storyboard.status = StoryboardDraftStatus.ARCHIVED
    storyboard.updated_at = utcnow()
    session.add(storyboard)
    session.commit()
    session.refresh(storyboard)
    return storyboard_payload(session, storyboard)


def script_document_payload(session: Session, document: ScriptDocument) -> dict[str, Any]:
    block_count = session.exec(select(ScriptBlock).where(ScriptBlock.script_document_id == document.id)).all()
    storyboard_count = session.exec(select(StoryboardDraft).where(StoryboardDraft.script_document_id == document.id)).all()
    return {
        **document.model_dump(exclude={"raw_text"}),
        "block_count": len(block_count),
        "storyboard_count": len(storyboard_count),
        "duplicate_of_id": None,
    }


def script_block_payload(block: ScriptBlock) -> dict[str, Any]:
    effective_type = block.user_block_type or block.block_type
    effective_text = block.user_normalized_text if block.user_normalized_text is not None else block.normalized_text
    return {
        **block.model_dump(),
        "effective_block_type": effective_type,
        "effective_text": effective_text,
        "metadata": loads_dict(block.metadata_json),
        "parse_warnings": loads_list(block.parse_warnings_json),
    }


def storyboard_payload(session: Session, storyboard: StoryboardDraft) -> dict[str, Any]:
    drafts = session.exec(select(ShotDraft).where(ShotDraft.storyboard_draft_id == storyboard.id)).all()
    return {
        **storyboard.model_dump(),
        "shot_draft_count": len(drafts),
        "applied_shot_count": len([item for item in drafts if item.applied_shot_id]),
    }


def shot_draft_payload(session: Session, draft: ShotDraft) -> dict[str, Any]:
    characters = session.exec(
        select(ShotDraftCharacter).where(ShotDraftCharacter.shot_draft_id == draft.id).order_by(col(ShotDraftCharacter.sort_order))
    ).all()
    return {
        **draft.model_dump(),
        "props": loads_list(draft.props_json),
        "characters": [draft_character_payload(item) for item in characters],
        "source_text": _draft_source_text(session, draft),
    }


def draft_character_payload(item: ShotDraftCharacter) -> dict[str, Any]:
    return {
        "character_id": item.character_id,
        "character_name": item.character_name,
        "role": item.role,
        "action": item.action,
        "expression": item.expression,
        "clothing": item.clothing,
        "position": item.position,
        "props": loads_list(item.props_json),
        "notes": item.notes,
        "sort_order": item.sort_order,
    }


def _extract_docx_text(content: bytes) -> str:
    settings = get_settings()
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
            total = sum(info.file_size for info in archive.infolist())
            if total > settings.script_max_docx_uncompressed_bytes:
                raise AppError("DOCX_TOO_LARGE", "DOCX uncompressed content exceeds the configured limit.", 413)
            xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise AppError("DOCX_INVALID", "DOCX document.xml is missing.", 400) from exc
    except zipfile.BadZipFile as exc:
        raise AppError("DOCX_INVALID", "DOCX file is not a valid zip document.", 400) from exc
    root = ElementTree.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns))
        if text:
            paragraphs.append(text)
    return _bounded_text("\n".join(paragraphs))


def _bounded_text(text: str) -> str:
    limit = get_settings().script_max_extracted_text_chars
    if len(text) > limit:
        raise AppError("SCRIPT_TEXT_TOO_LARGE", "Extracted script text is larger than the configured limit.", 413)
    return text


def _title_from_filename(filename: str) -> str:
    name = Path(filename).name
    return Path(name).stem if name else ""


def _replace_draft_characters(session: Session, draft: ShotDraft, characters: list[ShotDraftCharacterInput]) -> None:
    for existing in session.exec(select(ShotDraftCharacter).where(ShotDraftCharacter.shot_draft_id == draft.id)).all():
        session.delete(existing)
    session.flush()
    project_id = _storyboard_project_id(session, draft)
    for index, payload in enumerate(characters):
        if payload.character_id is not None:
            character = session.get(Character, payload.character_id)
            if character is None or character.project_id != project_id:
                raise AppError("CHARACTER_NOT_FOUND", "Character was not found in this project.", 404)
        session.add(
            ShotDraftCharacter(
                shot_draft_id=draft.id or 0,
                character_id=payload.character_id,
                character_name=payload.character_name,
                role=payload.role,
                action=payload.action,
                expression=payload.expression,
                clothing=payload.clothing,
                position=payload.position,
                props_json=dumps(payload.props),
                notes=payload.notes,
                sort_order=payload.sort_order if payload.sort_order else index,
            )
        )


def _apply_draft_to_spec(session: Session, draft: ShotDraft, shot: Shot, spec: ShotSpec) -> None:
    spec.location_id = draft.location_id
    spec.style_profile_id = draft.style_profile_id
    spec.summary = draft.summary
    spec.action = draft.action
    spec.emotion = draft.emotion
    spec.composition = draft.composition
    spec.shot_size = draft.shot_size
    spec.camera_angle = draft.camera_angle
    spec.camera_movement = draft.camera_movement
    spec.lighting = draft.lighting
    spec.time_of_day = draft.time_of_day
    spec.weather = draft.weather
    spec.dialogue = draft.dialogue
    spec.continuity_notes = draft.continuity_notes
    spec.props_json = draft.props_json
    session.add(spec)
    session.flush()
    shot.description = draft.summary
    shot.duration_seconds = draft.suggested_duration_seconds
    shot.prompt = draft.free_prompt
    shot.negative_prompt = draft.negative_prompt
    session.add(shot)
    _replace_shot_spec_characters_from_draft(session, draft, spec)
    structured.compile_and_store_spec(session, shot, spec)


def _replace_shot_spec_characters_from_draft(session: Session, draft: ShotDraft, spec: ShotSpec) -> None:
    for existing in session.exec(select(ShotCharacter).where(ShotCharacter.shot_spec_id == spec.id)).all():
        session.delete(existing)
    session.flush()
    inputs = []
    for item in session.exec(
        select(ShotDraftCharacter).where(ShotDraftCharacter.shot_draft_id == draft.id).order_by(col(ShotDraftCharacter.sort_order))
    ).all():
        if item.character_id is None:
            continue
        inputs.append(
            ShotCharacterInput(
                character_id=item.character_id,
                role=item.role,
                sort_order=item.sort_order,
                clothing_override=item.clothing,
                expression=item.expression,
                action=item.action,
                position=item.position,
                props=loads_list(item.props_json),
                continuity_notes=item.notes,
            )
        )
    structured.replace_shot_characters(session, spec, inputs)


def _draft_prompt_characters(session: Session, draft: ShotDraft) -> list[CharacterPromptInput]:
    result: list[CharacterPromptInput] = []
    for item in session.exec(
        select(ShotDraftCharacter).where(ShotDraftCharacter.shot_draft_id == draft.id).order_by(col(ShotDraftCharacter.sort_order))
    ).all():
        character = session.get(Character, item.character_id) if item.character_id else None
        result.append(
            CharacterPromptInput(
                character_id=character.id if character else None,
                name=character.name if character else item.character_name,
                role=item.role.value,
                sort_order=item.sort_order,
                appearance=character.appearance if character else "",
                clothing=item.clothing or (character.default_clothing if character else ""),
                expression=item.expression,
                action=item.action,
                position=item.position,
                props=loads_list(item.props_json),
                continuity_notes=item.notes or (character.continuity_notes if character else ""),
                reference_asset_ids=structured.ordered_character_reference_ids(session, character.id or 0, explicit_ids=[])
                if character
                else [],
            )
        )
    return result


def _draft_spec(draft: ShotDraft, *, shot_id: int) -> ShotSpec:
    return ShotSpec(
        shot_id=shot_id,
        revision=1,
        location_id=draft.location_id,
        style_profile_id=draft.style_profile_id,
        summary=draft.summary,
        action=draft.action,
        emotion=draft.emotion,
        composition=draft.composition,
        shot_size=draft.shot_size,
        camera_angle=draft.camera_angle,
        camera_movement=draft.camera_movement,
        lighting=draft.lighting,
        time_of_day=draft.time_of_day,
        weather=draft.weather,
        dialogue=draft.dialogue,
        continuity_notes=draft.continuity_notes,
        props_json=draft.props_json,
    )


def _ensure_draft_editable(draft: ShotDraft) -> None:
    if draft.status == ShotDraftStatus.APPLIED:
        raise AppError("SHOT_DRAFT_ALREADY_APPLIED", "Applied drafts cannot be edited.", 409)


def _storyboard_project_id(session: Session, draft: ShotDraft) -> int:
    storyboard = get_storyboard_or_404(session, draft.storyboard_draft_id)
    return storyboard.project_id


def _validate_location(session: Session, draft: ShotDraft, location_id: int) -> None:
    location = session.get(Location, location_id)
    if location is None or location.project_id != _storyboard_project_id(session, draft):
        raise AppError("LOCATION_NOT_FOUND", "Location was not found in this project.", 404)


def _validate_style(session: Session, draft: ShotDraft, style_id: int) -> None:
    style = session.get(StyleProfile, style_id)
    if style is None or style.project_id != _storyboard_project_id(session, draft):
        raise AppError("STYLE_PROFILE_NOT_FOUND", "StyleProfile was not found in this project.", 404)


def _ensure_can_apply(session: Session, project_id: int) -> None:
    active_task = session.exec(
        select(GenerationTask).where(
            GenerationTask.project_id == project_id,
            col(GenerationTask.status).in_(
                [
                    ReliableTaskStatus.QUEUED,
                    ReliableTaskStatus.SUBMITTING,
                    ReliableTaskStatus.RUNNING,
                    ReliableTaskStatus.RETRY_WAIT,
                    ReliableTaskStatus.RESULT_READY,
                    ReliableTaskStatus.PROCESSING_RESULT,
                    ReliableTaskStatus.CANCELLING,
                ]
            ),
        )
    ).first()
    if active_task is not None:
        raise AppError("ACTIVE_TASKS_BLOCK_STORYBOARD_APPLY", "Active generation tasks block storyboard apply.", 409)
    active_render = session.exec(
        select(ProjectRender).where(
            ProjectRender.project_id == project_id,
            col(ProjectRender.status).in_(["QUEUED", "PREPARING", "NORMALIZING", "CONCATENATING", "VALIDATING", "FINALIZING"]),
        )
    ).first()
    if active_render is not None:
        raise AppError("ACTIVE_RENDER_BLOCK_STORYBOARD_APPLY", "Active render blocks storyboard apply.", 409)


def _move_shot_after(session: Session, shot: Shot, insert_after_shot_id: int) -> None:
    anchor = session.get(Shot, insert_after_shot_id)
    if anchor is None or anchor.project_id != shot.project_id:
        raise AppError("INSERT_ANCHOR_NOT_FOUND", "Insert anchor Shot was not found in this project.", 404)
    target_order = anchor.sort_order + 1
    for item in session.exec(
        select(Shot).where(Shot.project_id == shot.project_id, Shot.id != shot.id, Shot.sort_order >= target_order).order_by(col(Shot.sort_order).desc())
    ).all():
        item.sort_order += 1
        session.add(item)
    shot.sort_order = target_order
    session.add(shot)
    session.flush()


def _refresh_storyboard_status(session: Session, storyboard_id: int) -> None:
    storyboard = get_storyboard_or_404(session, storyboard_id)
    drafts = session.exec(select(ShotDraft).where(ShotDraft.storyboard_draft_id == storyboard_id)).all()
    applied = [item for item in drafts if item.status == ShotDraftStatus.APPLIED]
    if applied and len(applied) == len(drafts):
        storyboard.status = StoryboardDraftStatus.APPLIED
        storyboard.applied_at = utcnow()
    elif applied:
        storyboard.status = StoryboardDraftStatus.PARTIALLY_APPLIED
    storyboard.updated_at = utcnow()
    session.add(storyboard)


def _block_ids_in_range(session: Session, start_id: int, end_id: int) -> list[int]:
    start = session.get(ScriptBlock, start_id)
    end = session.get(ScriptBlock, end_id)
    if start is None or end is None or start.script_document_id != end.script_document_id:
        return []
    blocks = session.exec(
        select(ScriptBlock)
        .where(
            ScriptBlock.script_document_id == start.script_document_id,
            ScriptBlock.parse_revision == start.parse_revision,
            ScriptBlock.sort_order >= start.sort_order,
            ScriptBlock.sort_order <= end.sort_order,
        )
        .order_by(col(ScriptBlock.sort_order))
    ).all()
    return [item.id or 0 for item in blocks]


def _shift_draft_orders(session: Session, storyboard_id: int, from_order: int) -> None:
    for item in session.exec(
        select(ShotDraft).where(ShotDraft.storyboard_draft_id == storyboard_id, ShotDraft.sort_order >= from_order).order_by(col(ShotDraft.sort_order).desc())
    ).all():
        item.sort_order += 1
        session.add(item)


def _draft_source_text(session: Session, draft: ShotDraft) -> str:
    if not draft.source_block_start_id or not draft.source_block_end_id:
        return ""
    ids = _block_ids_in_range(session, draft.source_block_start_id, draft.source_block_end_id)
    if not ids:
        return ""
    blocks = session.exec(select(ScriptBlock).where(col(ScriptBlock.id).in_(ids)).order_by(col(ScriptBlock.sort_order))).all()
    return "".join(item.source_text for item in blocks)


def _join_text(left: str, right: str, *, max_len: int) -> str:
    return "\n".join(part for part in (left, right) if part).strip()[:max_len]


def _unique(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
