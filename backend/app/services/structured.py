import json
from typing import Any

from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.domain.prompt_compiler import CharacterPromptInput, PromptCompileInput, compile_shot_prompt
from app.models.entities import (
    Asset,
    AssetStatus,
    Character,
    CharacterReference,
    Location,
    LocationReference,
    Project,
    Shot,
    ShotCharacter,
    ShotCharacterRole,
    ShotSpec,
    StyleProfile,
    utcnow,
)
from app.models.schemas import (
    CharacterCreate,
    CharacterReferenceCreate,
    CharacterUpdate,
    LocationCreate,
    LocationReferenceCreate,
    LocationUpdate,
    ShotCharacterInput,
    ShotSpecRevisionRequest,
    StyleProfileCreate,
    StyleProfileUpdate,
)


SPEC_FIELDS = {
    "location_id",
    "style_profile_id",
    "summary",
    "action",
    "emotion",
    "composition",
    "shot_size",
    "camera_angle",
    "camera_movement",
    "lighting",
    "time_of_day",
    "weather",
    "dialogue",
    "continuity_notes",
    "props",
    "provider_overrides",
}


def get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("PROJECT_NOT_FOUND", f"Project {project_id} was not found.", 404)
    return project


def list_characters(session: Session, project_id: int, *, include_archived: bool = False) -> list[dict[str, Any]]:
    get_project_or_404(session, project_id)
    statement = select(Character).where(Character.project_id == project_id)
    if not include_archived:
        statement = statement.where(col(Character.archived_at).is_(None))
    return [character_payload(session, item) for item in session.exec(statement.order_by(col(Character.name))).all()]


def create_character(session: Session, project_id: int, payload: CharacterCreate) -> dict[str, Any]:
    get_project_or_404(session, project_id)
    character = Character(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        appearance=payload.appearance,
        personality=payload.personality,
        default_clothing=payload.default_clothing,
        default_props_json=dumps(payload.default_props),
        continuity_notes=payload.continuity_notes,
    )
    session.add(character)
    session.commit()
    session.refresh(character)
    return character_payload(session, character)


def get_character_payload(session: Session, character_id: int) -> dict[str, Any]:
    return character_payload(session, get_character_or_404(session, character_id))


def update_character(session: Session, character_id: int, payload: CharacterUpdate) -> dict[str, Any]:
    character = get_character_or_404(session, character_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "default_props":
            character.default_props_json = dumps(value or [])
        else:
            setattr(character, key, value)
    character.updated_at = utcnow()
    session.add(character)
    session.commit()
    session.refresh(character)
    return character_payload(session, character)


def archive_character(session: Session, character_id: int) -> None:
    character = get_character_or_404(session, character_id)
    character.archived_at = character.archived_at or utcnow()
    character.updated_at = utcnow()
    session.add(character)
    session.commit()


def add_character_reference(
    session: Session, character_id: int, payload: CharacterReferenceCreate
) -> dict[str, Any]:
    character = get_character_or_404(session, character_id)
    asset = valid_image_asset(session, payload.asset_id, project_id=character.project_id)
    if payload.is_primary:
        for ref in session.exec(
            select(CharacterReference).where(CharacterReference.character_id == character_id, CharacterReference.is_primary)
        ).all():
            ref.is_primary = False
            session.add(ref)
    reference = CharacterReference(
        character_id=character_id,
        asset_id=asset.id or 0,
        reference_type=payload.reference_type,
        label=payload.label,
        is_primary=payload.is_primary,
        sort_order=payload.sort_order,
    )
    session.add(reference)
    session.commit()
    session.refresh(reference)
    return character_reference_payload(reference)


def delete_character_reference(session: Session, reference_id: int) -> None:
    reference = session.get(CharacterReference, reference_id)
    if reference is None:
        raise AppError("REFERENCE_NOT_FOUND", f"Character reference {reference_id} was not found.", 404)
    session.delete(reference)
    session.commit()


def list_locations(session: Session, project_id: int, *, include_archived: bool = False) -> list[dict[str, Any]]:
    get_project_or_404(session, project_id)
    statement = select(Location).where(Location.project_id == project_id)
    if not include_archived:
        statement = statement.where(col(Location.archived_at).is_(None))
    return [location_payload(session, item) for item in session.exec(statement.order_by(col(Location.name))).all()]


def create_location(session: Session, project_id: int, payload: LocationCreate) -> dict[str, Any]:
    get_project_or_404(session, project_id)
    location = Location(project_id=project_id, **payload.model_dump())
    session.add(location)
    session.commit()
    session.refresh(location)
    return location_payload(session, location)


def get_location_payload(session: Session, location_id: int) -> dict[str, Any]:
    return location_payload(session, get_location_or_404(session, location_id))


def update_location(session: Session, location_id: int, payload: LocationUpdate) -> dict[str, Any]:
    location = get_location_or_404(session, location_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, key, value)
    location.updated_at = utcnow()
    session.add(location)
    session.commit()
    session.refresh(location)
    return location_payload(session, location)


def archive_location(session: Session, location_id: int) -> None:
    location = get_location_or_404(session, location_id)
    location.archived_at = location.archived_at or utcnow()
    location.updated_at = utcnow()
    session.add(location)
    session.commit()


def add_location_reference(session: Session, location_id: int, payload: LocationReferenceCreate) -> dict[str, Any]:
    location = get_location_or_404(session, location_id)
    asset = valid_image_asset(session, payload.asset_id, project_id=location.project_id)
    if payload.is_primary:
        for ref in session.exec(
            select(LocationReference).where(LocationReference.location_id == location_id, LocationReference.is_primary)
        ).all():
            ref.is_primary = False
            session.add(ref)
    reference = LocationReference(
        location_id=location_id,
        asset_id=asset.id or 0,
        reference_type=payload.reference_type,
        label=payload.label,
        is_primary=payload.is_primary,
        sort_order=payload.sort_order,
    )
    session.add(reference)
    session.commit()
    session.refresh(reference)
    return location_reference_payload(reference)


def delete_location_reference(session: Session, reference_id: int) -> None:
    reference = session.get(LocationReference, reference_id)
    if reference is None:
        raise AppError("REFERENCE_NOT_FOUND", f"Location reference {reference_id} was not found.", 404)
    session.delete(reference)
    session.commit()


def list_style_profiles(session: Session, project_id: int, *, include_archived: bool = False) -> list[dict[str, Any]]:
    get_project_or_404(session, project_id)
    statement = select(StyleProfile).where(StyleProfile.project_id == project_id)
    if not include_archived:
        statement = statement.where(col(StyleProfile.archived_at).is_(None))
    return [style_profile_payload(session, item) for item in session.exec(statement.order_by(col(StyleProfile.name))).all()]


def create_style_profile(session: Session, project_id: int, payload: StyleProfileCreate) -> dict[str, Any]:
    get_project_or_404(session, project_id)
    style = StyleProfile(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        positive_prompt=payload.positive_prompt,
        negative_prompt=payload.negative_prompt,
        color_palette_json=dumps(payload.color_palette),
        rendering_style=payload.rendering_style,
        camera_language=payload.camera_language,
        aspect_ratio=payload.aspect_ratio,
        fps=payload.fps,
        default_provider_options_json=dumps(payload.default_provider_options),
    )
    session.add(style)
    session.commit()
    session.refresh(style)
    return style_profile_payload(session, style)


def get_style_profile_payload(session: Session, style_profile_id: int) -> dict[str, Any]:
    return style_profile_payload(session, get_style_profile_or_404(session, style_profile_id))


def update_style_profile(session: Session, style_profile_id: int, payload: StyleProfileUpdate) -> dict[str, Any]:
    style = get_style_profile_or_404(session, style_profile_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "color_palette":
            style.color_palette_json = dumps(value or [])
        elif key == "default_provider_options":
            style.default_provider_options_json = dumps(value or {})
        else:
            setattr(style, key, value)
    style.updated_at = utcnow()
    session.add(style)
    session.commit()
    session.refresh(style)
    return style_profile_payload(session, style)


def archive_style_profile(session: Session, style_profile_id: int) -> None:
    style = get_style_profile_or_404(session, style_profile_id)
    style.archived_at = style.archived_at or utcnow()
    style.updated_at = utcnow()
    session.add(style)
    session.commit()


def create_initial_shot_spec(session: Session, shot: Shot, *, commit: bool = True) -> ShotSpec:
    existing = get_current_shot_spec(session, shot)
    if existing is not None:
        return existing
    spec = ShotSpec(
        shot_id=shot.id or 0,
        revision=shot.spec_revision,
        summary=shot.description,
        continuity_notes=shot.description,
    )
    session.add(spec)
    session.flush()
    compile_and_store_spec(session, shot, spec)
    if commit:
        session.commit()
        session.refresh(spec)
    return spec


def get_current_shot_spec(session: Session, shot: Shot) -> ShotSpec | None:
    return session.exec(
        select(ShotSpec).where(ShotSpec.shot_id == shot.id, ShotSpec.revision == shot.spec_revision)
    ).first()


def get_shot_spec_payload(session: Session, shot_id: int) -> dict[str, Any]:
    shot = get_shot_or_404(session, shot_id)
    spec = create_initial_shot_spec(session, shot)
    return shot_spec_payload(session, spec)


def list_shot_spec_history(session: Session, shot_id: int) -> list[dict[str, Any]]:
    get_shot_or_404(session, shot_id)
    specs = session.exec(select(ShotSpec).where(ShotSpec.shot_id == shot_id).order_by(col(ShotSpec.revision))).all()
    return [shot_spec_payload(session, spec) for spec in specs]


def create_revised_shot_spec(
    session: Session,
    shot: Shot,
    *,
    previous_revision: int,
    payload: ShotSpecRevisionRequest,
) -> ShotSpec:
    previous = session.exec(
        select(ShotSpec).where(ShotSpec.shot_id == shot.id, ShotSpec.revision == previous_revision)
    ).first()
    if previous is None:
        previous = create_initial_shot_spec(session, shot, commit=False)
    spec = clone_spec(previous, revision=shot.spec_revision)
    for key, value in payload.changes.items():
        if key not in SPEC_FIELDS:
            raise AppError("INVALID_SHOT_SPEC_FIELD", f"Unsupported ShotSpec field: {key}.", 400)
        if key == "props":
            spec.props_json = dumps(value if isinstance(value, list) else [])
        elif key == "provider_overrides":
            spec.provider_overrides_json = dumps(value if isinstance(value, dict) else {})
        else:
            setattr(spec, key, "" if value is None else str(value))
    session.add(spec)
    session.flush()
    if payload.characters is None:
        copy_shot_characters(session, previous.id or 0, spec.id or 0)
    else:
        replace_shot_characters(session, spec, payload.characters)
    compile_and_store_spec(session, shot, spec)
    session.add(spec)
    session.flush()
    return spec


def sync_shot_spec(
    session: Session,
    shot: Shot,
    *,
    previous_revision: int,
    sync_character_defaults: bool,
    sync_location_defaults: bool,
    sync_style_profile: bool,
) -> ShotSpec:
    previous = session.exec(
        select(ShotSpec).where(ShotSpec.shot_id == shot.id, ShotSpec.revision == previous_revision)
    ).first()
    if previous is None:
        previous = create_initial_shot_spec(session, shot, commit=False)
    spec = clone_spec(previous, revision=shot.spec_revision)
    session.add(spec)
    session.flush()
    characters = list(
        session.exec(select(ShotCharacter).where(ShotCharacter.shot_spec_id == previous.id).order_by(col(ShotCharacter.sort_order))).all()
    )
    for item in characters:
        source_character = session.get(Character, item.character_id)
        copied = ShotCharacter(
            shot_spec_id=spec.id or 0,
            character_id=item.character_id,
            role=item.role,
            sort_order=item.sort_order,
            appearance_override=source_character.appearance if sync_character_defaults and source_character else item.appearance_override,
            clothing_override=source_character.default_clothing
            if sync_character_defaults and source_character
            else item.clothing_override,
            expression=item.expression,
            action=item.action,
            position=item.position,
            props_json=source_character.default_props_json
            if sync_character_defaults and source_character
            else item.props_json,
            continuity_notes=source_character.continuity_notes
            if sync_character_defaults and source_character
            else item.continuity_notes,
            reference_asset_ids_json=item.reference_asset_ids_json,
        )
        session.add(copied)
    if sync_location_defaults and spec.location_id:
        location = session.get(Location, spec.location_id)
        if location:
            spec.time_of_day = location.time_of_day
            spec.weather = location.weather
            spec.lighting = location.lighting
    if sync_style_profile and spec.style_profile_id:
        style = session.get(StyleProfile, spec.style_profile_id)
        if style and style.aspect_ratio:
            overrides = loads_dict(spec.provider_overrides_json)
            overrides["aspect_ratio"] = style.aspect_ratio
            if style.fps:
                overrides["fps"] = style.fps
            spec.provider_overrides_json = dumps(overrides)
    compile_and_store_spec(session, shot, spec)
    session.flush()
    return spec


def synced_spec_matches_current(
    session: Session,
    shot: Shot,
    *,
    sync_character_defaults: bool,
    sync_location_defaults: bool,
    sync_style_profile: bool,
) -> bool:
    current = get_current_shot_spec(session, shot)
    if current is None:
        return False
    candidate = clone_spec(current, revision=current.revision)
    characters = _synced_character_inputs(
        session,
        current.id or 0,
        sync_character_defaults=sync_character_defaults,
    )
    if sync_location_defaults and candidate.location_id:
        location = session.get(Location, candidate.location_id)
        if location:
            candidate.time_of_day = location.time_of_day
            candidate.weather = location.weather
            candidate.lighting = location.lighting
    if sync_style_profile and candidate.style_profile_id:
        style = session.get(StyleProfile, candidate.style_profile_id)
        if style:
            overrides = loads_dict(candidate.provider_overrides_json)
            if style.aspect_ratio:
                overrides["aspect_ratio"] = style.aspect_ratio
            if style.fps:
                overrides["fps"] = style.fps
            candidate.provider_overrides_json = dumps(overrides)
    result = compile_shot_prompt(build_compile_input(session, shot, candidate, character_inputs=characters))
    return (
        current.compiled_prompt == result.compiled_prompt
        and current.compiled_negative_prompt == result.compiled_negative_prompt
        and current.compiler_version == result.compiler_version
        and loads_dict(current.structured_payload_json) == result.structured_payload
    )


def compile_and_store_spec(session: Session, shot: Shot, spec: ShotSpec) -> ShotSpec:
    result = compile_shot_prompt(build_compile_input(session, shot, spec))
    spec.compiled_prompt = result.compiled_prompt
    spec.compiled_negative_prompt = result.compiled_negative_prompt
    spec.compiler_version = result.compiler_version
    spec.structured_payload_json = dumps(result.structured_payload)
    session.add(spec)
    session.flush()
    return spec


def build_compile_input(
    session: Session,
    shot: Shot,
    spec: ShotSpec,
    *,
    character_inputs: list[CharacterPromptInput] | None = None,
) -> PromptCompileInput:
    location = session.get(Location, spec.location_id) if spec.location_id else None
    style = session.get(StyleProfile, spec.style_profile_id) if spec.style_profile_id else None
    characters = character_inputs if character_inputs is not None else []
    reference_asset_ids: list[int] = []
    if character_inputs is None:
        for item in session.exec(
            select(ShotCharacter).where(ShotCharacter.shot_spec_id == spec.id).order_by(col(ShotCharacter.sort_order), col(ShotCharacter.id))
        ).all():
            character = session.get(Character, item.character_id)
            if character is None:
                continue
            item_refs = ordered_character_reference_ids(session, character.id or 0, explicit_ids=loads_list(item.reference_asset_ids_json))
            reference_asset_ids.extend(item_refs)
            characters.append(
                CharacterPromptInput(
                    character_id=character.id,
                    name=character.name,
                    role=item.role.value,
                    sort_order=item.sort_order,
                    appearance=item.appearance_override or character.appearance,
                    clothing=item.clothing_override or character.default_clothing,
                    expression=item.expression,
                    action=item.action,
                    position=item.position,
                    props=loads_list(item.props_json) or loads_list(character.default_props_json),
                    continuity_notes=item.continuity_notes or character.continuity_notes,
                    reference_asset_ids=item_refs,
                )
            )
    else:
        for prompt_character in characters:
            reference_asset_ids.extend(prompt_character.reference_asset_ids or [])
    if location:
        reference_asset_ids.extend(ordered_location_reference_ids(session, location.id or 0))
    return PromptCompileInput(
        shot_revision=spec.revision,
        shot_title=shot.title,
        shot_prompt=shot.prompt,
        shot_negative_prompt=shot.negative_prompt,
        style_positive_prompt=style.positive_prompt if style else "",
        style_negative_prompt=style.negative_prompt if style else "",
        style_rendering=style.rendering_style if style else "",
        style_camera_language=style.camera_language if style else "",
        location_name=location.name if location else "",
        location_description=location.description if location else "",
        location_environment=location.environment if location else "",
        location_architecture=location.architecture if location else "",
        location_time_of_day=location.time_of_day if location else "",
        location_weather=location.weather if location else "",
        location_lighting=location.lighting if location else "",
        summary=spec.summary,
        action=spec.action,
        emotion=spec.emotion,
        composition=spec.composition,
        shot_size=spec.shot_size,
        camera_angle=spec.camera_angle,
        camera_movement=spec.camera_movement,
        lighting=spec.lighting,
        time_of_day=spec.time_of_day,
        weather=spec.weather,
        dialogue=spec.dialogue,
        continuity_notes=spec.continuity_notes,
        props=loads_list(spec.props_json),
        provider_overrides=loads_dict(spec.provider_overrides_json),
        characters=characters,
        reference_asset_ids=reference_asset_ids,
    )


def clone_spec(spec: ShotSpec, *, revision: int) -> ShotSpec:
    return ShotSpec(
        shot_id=spec.shot_id,
        revision=revision,
        location_id=spec.location_id,
        style_profile_id=spec.style_profile_id,
        summary=spec.summary,
        action=spec.action,
        emotion=spec.emotion,
        composition=spec.composition,
        shot_size=spec.shot_size,
        camera_angle=spec.camera_angle,
        camera_movement=spec.camera_movement,
        lighting=spec.lighting,
        time_of_day=spec.time_of_day,
        weather=spec.weather,
        dialogue=spec.dialogue,
        continuity_notes=spec.continuity_notes,
        props_json=spec.props_json,
        provider_overrides_json=spec.provider_overrides_json,
    )


def replace_shot_characters(session: Session, spec: ShotSpec, characters: list[ShotCharacterInput]) -> None:
    seen: set[int] = set()
    for index, payload in enumerate(characters):
        character = get_character_or_404(session, payload.character_id)
        shot = get_shot_or_404(session, spec.shot_id)
        if character.project_id != shot.project_id:
            raise AppError("CROSS_PROJECT_REFERENCE", "Character belongs to another project.", 409)
        if payload.character_id in seen:
            raise AppError("DUPLICATE_SHOT_CHARACTER", "Character appears more than once in this ShotSpec.", 409)
        seen.add(payload.character_id)
        validate_reference_asset_ids(session, payload.reference_asset_ids, project_id=shot.project_id)
        session.add(
            ShotCharacter(
                shot_spec_id=spec.id or 0,
                character_id=payload.character_id,
                role=payload.role,
                sort_order=payload.sort_order if payload.sort_order else index,
                appearance_override=payload.appearance_override,
                clothing_override=payload.clothing_override,
                expression=payload.expression,
                action=payload.action,
                position=payload.position,
                props_json=dumps(payload.props),
                continuity_notes=payload.continuity_notes,
                reference_asset_ids_json=dumps(payload.reference_asset_ids),
            )
        )


def copy_shot_characters(session: Session, old_spec_id: int, new_spec_id: int) -> None:
    for item in session.exec(
        select(ShotCharacter).where(ShotCharacter.shot_spec_id == old_spec_id).order_by(col(ShotCharacter.sort_order))
    ).all():
        session.add(
            ShotCharacter(
                shot_spec_id=new_spec_id,
                character_id=item.character_id,
                role=item.role,
                sort_order=item.sort_order,
                appearance_override=item.appearance_override,
                clothing_override=item.clothing_override,
                expression=item.expression,
                action=item.action,
                position=item.position,
                props_json=item.props_json,
                continuity_notes=item.continuity_notes,
                reference_asset_ids_json=item.reference_asset_ids_json,
            )
        )


def _synced_character_inputs(
    session: Session,
    old_spec_id: int,
    *,
    sync_character_defaults: bool,
) -> list[CharacterPromptInput]:
    result: list[CharacterPromptInput] = []
    for item in session.exec(
        select(ShotCharacter).where(ShotCharacter.shot_spec_id == old_spec_id).order_by(col(ShotCharacter.sort_order), col(ShotCharacter.id))
    ).all():
        character = session.get(Character, item.character_id)
        if character is None:
            continue
        reference_ids = ordered_character_reference_ids(session, character.id or 0, explicit_ids=loads_list(item.reference_asset_ids_json))
        result.append(
            CharacterPromptInput(
                character_id=character.id,
                name=character.name,
                role=item.role.value,
                sort_order=item.sort_order,
                appearance=character.appearance if sync_character_defaults else item.appearance_override or character.appearance,
                clothing=character.default_clothing if sync_character_defaults else item.clothing_override or character.default_clothing,
                expression=item.expression,
                action=item.action,
                position=item.position,
                props=loads_list(character.default_props_json)
                if sync_character_defaults
                else loads_list(item.props_json) or loads_list(character.default_props_json),
                continuity_notes=character.continuity_notes
                if sync_character_defaults
                else item.continuity_notes or character.continuity_notes,
                reference_asset_ids=reference_ids,
            )
        )
    return result


def ordered_character_reference_ids(session: Session, character_id: int, *, explicit_ids: list[Any]) -> list[int]:
    ids: list[int] = [item for item in explicit_ids if isinstance(item, int)]
    refs = list(
        session.exec(
            select(CharacterReference)
            .where(CharacterReference.character_id == character_id)
            .order_by(col(CharacterReference.sort_order), col(CharacterReference.id))
        ).all()
    )
    primary = [ref.asset_id for ref in refs if ref.is_primary]
    others = [ref.asset_id for ref in refs if not ref.is_primary]
    return unique_ints(ids + primary + others)


def ordered_location_reference_ids(session: Session, location_id: int) -> list[int]:
    refs = list(
        session.exec(
            select(LocationReference)
            .where(LocationReference.location_id == location_id)
            .order_by(col(LocationReference.sort_order), col(LocationReference.id))
        ).all()
    )
    primary = [ref.asset_id for ref in refs if ref.is_primary]
    others = [ref.asset_id for ref in refs if not ref.is_primary]
    return unique_ints(primary + others)


def unique_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if not isinstance(value, int) or value <= 0 or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def selected_reference_assets(session: Session, shot: Shot, *, max_count: int) -> tuple[list[int], int]:
    spec = create_initial_shot_spec(session, shot)
    payload = loads_dict(spec.structured_payload_json)
    ids = [item for item in payload.get("reference_asset_ids", []) if isinstance(item, int)]
    valid = [asset_id for asset_id in ids if reference_asset_is_valid(session, asset_id, shot.project_id)]
    return valid[:max_count], max(len(valid) - max_count, 0)


def shot_spec_payload(session: Session, spec: ShotSpec) -> dict[str, Any]:
    characters = list(
        session.exec(select(ShotCharacter).where(ShotCharacter.shot_spec_id == spec.id).order_by(col(ShotCharacter.sort_order))).all()
    )
    structured_payload = loads_dict(spec.structured_payload_json)
    return {
        "id": spec.id,
        "shot_id": spec.shot_id,
        "revision": spec.revision,
        "location_id": spec.location_id,
        "style_profile_id": spec.style_profile_id,
        "summary": spec.summary,
        "action": spec.action,
        "emotion": spec.emotion,
        "composition": spec.composition,
        "shot_size": spec.shot_size,
        "camera_angle": spec.camera_angle,
        "camera_movement": spec.camera_movement,
        "lighting": spec.lighting,
        "time_of_day": spec.time_of_day,
        "weather": spec.weather,
        "dialogue": spec.dialogue,
        "continuity_notes": spec.continuity_notes,
        "props": loads_list(spec.props_json),
        "provider_overrides": loads_dict(spec.provider_overrides_json),
        "compiled_prompt": spec.compiled_prompt,
        "compiled_negative_prompt": spec.compiled_negative_prompt,
        "structured_payload_json": spec.structured_payload_json,
        "structured_payload": structured_payload,
        "compiler_version": spec.compiler_version,
        "created_at": spec.created_at,
        "characters": snapshot_character_payloads(structured_payload, characters),
        "reference_asset_ids": [item for item in structured_payload.get("reference_asset_ids", []) if isinstance(item, int)],
    }


def snapshot_character_payloads(structured_payload: dict[str, Any], characters: list[ShotCharacter]) -> list[dict[str, Any]]:
    snapshots = structured_payload.get("characters")
    if isinstance(snapshots, list) and snapshots:
        result: list[dict[str, Any]] = []
        for index, item in enumerate(snapshots):
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    "id": None,
                    "shot_spec_id": None,
                    "character_id": item.get("character_id"),
                    "role": item.get("role", ShotCharacterRole.SECONDARY.value),
                    "sort_order": item.get("sort_order", index),
                    "appearance_override": item.get("appearance", ""),
                    "clothing_override": item.get("clothing", ""),
                    "expression": item.get("expression", ""),
                    "action": item.get("action", ""),
                    "position": item.get("position", ""),
                    "props": item.get("props", []),
                    "continuity_notes": item.get("continuity_notes", ""),
                    "reference_asset_ids": item.get("reference_asset_ids", []),
                    "name_snapshot": item.get("name", ""),
                }
            )
        return result
    return [shot_character_payload(item) for item in characters]


def character_payload(session: Session, character: Character) -> dict[str, Any]:
    references = session.exec(select(CharacterReference).where(CharacterReference.character_id == character.id)).all()
    usage_count = session.exec(select(ShotCharacter).where(ShotCharacter.character_id == character.id)).all()
    primary = next((item for item in references if item.is_primary), None)
    return {
        "id": character.id,
        "project_id": character.project_id,
        "name": character.name,
        "description": character.description,
        "appearance": character.appearance,
        "personality": character.personality,
        "default_clothing": character.default_clothing,
        "default_props": loads_list(character.default_props_json),
        "continuity_notes": character.continuity_notes,
        "archived_at": character.archived_at,
        "created_at": character.created_at,
        "updated_at": character.updated_at,
        "usage_count": len(usage_count),
        "reference_count": len(references),
        "primary_reference_asset_id": primary.asset_id if primary else None,
    }


def location_payload(session: Session, location: Location) -> dict[str, Any]:
    references = session.exec(select(LocationReference).where(LocationReference.location_id == location.id)).all()
    usage_count = session.exec(select(ShotSpec).where(ShotSpec.location_id == location.id)).all()
    primary = next((item for item in references if item.is_primary), None)
    return {
        **location.model_dump(),
        "usage_count": len(usage_count),
        "reference_count": len(references),
        "primary_reference_asset_id": primary.asset_id if primary else None,
    }


def style_profile_payload(session: Session, style: StyleProfile) -> dict[str, Any]:
    usage_count = session.exec(select(ShotSpec).where(ShotSpec.style_profile_id == style.id)).all()
    return {
        "id": style.id,
        "project_id": style.project_id,
        "name": style.name,
        "description": style.description,
        "positive_prompt": style.positive_prompt,
        "negative_prompt": style.negative_prompt,
        "color_palette": loads_list(style.color_palette_json),
        "rendering_style": style.rendering_style,
        "camera_language": style.camera_language,
        "aspect_ratio": style.aspect_ratio,
        "fps": style.fps,
        "default_provider_options": loads_dict(style.default_provider_options_json),
        "archived_at": style.archived_at,
        "created_at": style.created_at,
        "updated_at": style.updated_at,
        "usage_count": len(usage_count),
    }


def character_reference_payload(reference: CharacterReference) -> dict[str, Any]:
    return reference.model_dump()


def location_reference_payload(reference: LocationReference) -> dict[str, Any]:
    return reference.model_dump()


def shot_character_payload(item: ShotCharacter) -> dict[str, Any]:
    return {
        "id": item.id,
        "shot_spec_id": item.shot_spec_id,
        "character_id": item.character_id,
        "role": item.role,
        "sort_order": item.sort_order,
        "appearance_override": item.appearance_override,
        "clothing_override": item.clothing_override,
        "expression": item.expression,
        "action": item.action,
        "position": item.position,
        "props": loads_list(item.props_json),
        "continuity_notes": item.continuity_notes,
        "reference_asset_ids": loads_list(item.reference_asset_ids_json),
    }


def get_character_or_404(session: Session, character_id: int) -> Character:
    character = session.get(Character, character_id)
    if character is None:
        raise AppError("CHARACTER_NOT_FOUND", f"Character {character_id} was not found.", 404)
    return character


def get_location_or_404(session: Session, location_id: int) -> Location:
    location = session.get(Location, location_id)
    if location is None:
        raise AppError("LOCATION_NOT_FOUND", f"Location {location_id} was not found.", 404)
    return location


def get_style_profile_or_404(session: Session, style_profile_id: int) -> StyleProfile:
    style = session.get(StyleProfile, style_profile_id)
    if style is None:
        raise AppError("STYLE_PROFILE_NOT_FOUND", f"Style profile {style_profile_id} was not found.", 404)
    return style


def get_shot_or_404(session: Session, shot_id: int) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise AppError("SHOT_NOT_FOUND", f"Shot {shot_id} was not found.", 404)
    return shot


def valid_image_asset(session: Session, asset_id: int, *, project_id: int) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise AppError("ASSET_NOT_FOUND", "Reference asset was not found in the same project.", 404)
    if asset.status in {AssetStatus.REJECTED, AssetStatus.STALE, AssetStatus.SUPERSEDED}:
        raise AppError("ASSET_NOT_CURRENT", "Reference asset is not current enough for library use.", 409)
    if asset.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise AppError("ASSET_NOT_IMAGE", "Reference asset must be a validated image.", 400)
    return asset


def validate_reference_asset_ids(session: Session, asset_ids: list[int], *, project_id: int) -> None:
    for asset_id in asset_ids:
        valid_image_asset(session, asset_id, project_id=project_id)


def reference_asset_is_valid(session: Session, asset_id: int, project_id: int) -> bool:
    try:
        valid_image_asset(session, asset_id, project_id=project_id)
    except AppError:
        return False
    return True


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
