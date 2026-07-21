from __future__ import annotations

import pytest
from sqlmodel import Session

from app.core.errors import AppError
from app.models.entities import Asset, AssetType, Project
from app.services.visual_experiment import (
    baseline_hash,
    create_baseline_draft,
    production_contracts,
    review_baseline,
)
from app.services.visual_regeneration import compile_prompts
from app.domain.visual_prompt_contract import VisualPromptContract


def add_image(session: Session, project_id: int, asset_id: int) -> None:
    session.add(
        Asset(
            id=asset_id,
            project_id=project_id,
            type=AssetType.KEYFRAME,
            path=f"asset-{asset_id}.png",
            mime_type="image/png",
            sha256=str(asset_id),
        )
    )
    session.commit()


def test_production_contracts_inherit_locks_and_isolate_motion() -> None:
    first, second = production_contracts()
    for lock in ("character", "camera", "environment", "style"):
        assert first[lock] == second[lock]
    assert first["motion"] != second["motion"]
    assert "head" in str(first["motion"]).lower()
    assert "arm" in str(second["motion"]).lower()


def test_motion_contracts_forbid_walk_cut_zoom_and_style_shift() -> None:
    first, second = production_contracts()
    forbidden = " ".join(first["motion"]["forbidden_motion"] + second["motion"]["forbidden_motion"])
    for value in ("walking", "scene cut", "zoom", "style shift"):
        assert value in forbidden


def test_prompt_hashes_are_stable_safe_and_shot_specific() -> None:
    first, second = production_contracts()
    a = compile_prompts(VisualPromptContract.model_validate(first), generation_kind="VIDEO")
    b = compile_prompts(VisualPromptContract.model_validate(second), generation_kind="VIDEO")
    assert a == compile_prompts(VisualPromptContract.model_validate(first), generation_kind="VIDEO")
    assert a["promptHash"] != b["promptHash"]
    assert "http" not in a["prompt"] and ":\\" not in a["prompt"]


def test_baseline_hash_is_stable_comment_independent_and_lock_sensitive() -> None:
    contract, _ = production_contracts()
    first = baseline_hash(83, "sha83", contract)
    assert first == baseline_hash(83, "sha83", contract)
    assert first != baseline_hash(89, "sha89", contract)
    changed = {**contract, "style": {**contract["style"], "detail_level": "changed"}}
    assert first != baseline_hash(83, "sha83", changed)


def test_draft_requires_project_image_and_excludes_asset_82(session: Session) -> None:
    project = Project(id=22, name="P")
    session.add(project)
    session.commit()
    add_image(session, 22, 82)
    with pytest.raises(AppError, match="excluded"):
        create_baseline_draft(session, project_id=22, source_asset_id=82)


def test_tail_asset_is_not_primary_candidate(session: Session) -> None:
    session.add(Project(id=22, name="P"))
    session.commit()
    add_image(session, 22, 87)
    with pytest.raises(AppError, match="primary baseline"):
        create_baseline_draft(session, project_id=22, source_asset_id=87)


def test_create_baseline_draft_is_pending_and_idempotent(session: Session) -> None:
    session.add(Project(id=22, name="P"))
    session.commit()
    add_image(session, 22, 83)
    first = create_baseline_draft(session, project_id=22, source_asset_id=83)
    second = create_baseline_draft(session, project_id=22, source_asset_id=83)
    assert first.id == second.id
    assert first.status == "READY_FOR_REVIEW"
    assert first.human_review_status == "PENDING"


def test_baseline_review_requires_acknowledgement_and_hash_match(session: Session) -> None:
    session.add(Project(id=22, name="P"))
    session.commit()
    add_image(session, 22, 83)
    draft = create_baseline_draft(session, project_id=22, source_asset_id=83)
    assert draft.id is not None
    with pytest.raises(AppError, match="acknowledgement"):
        review_baseline(
            session, baseline_id=draft.id, expected_hash=draft.baseline_hash, decision="APPROVED"
        )
    session.refresh(draft)
    assert draft.human_review_status == "PENDING"
    with pytest.raises(AppError, match="changed"):
        review_baseline(
            session,
            baseline_id=draft.id,
            expected_hash="0" * 64,
            decision="APPROVED",
            acknowledged=True,
        )
