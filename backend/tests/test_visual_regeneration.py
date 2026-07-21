from __future__ import annotations

from app.domain.visual_prompt_contract import MotionDelta
from app.services.visual_regeneration import compile_prompts, project_22_contract


def test_project_contract_is_complete_and_deterministic() -> None:
    first = project_22_contract()
    second = project_22_contract()
    first.validate_for_production()
    assert first.contract_hash() == second.contract_hash()
    assert first.inherit_for_next_shot(MotionDelta(
        starting_pose="a", ending_pose="b", allowed_motion="small", maximum_position_change="2%",
        maximum_scale_change="1%", forbidden_motion=["cut"],
    )).character == first.character


def test_motion_is_independent_between_shots() -> None:
    first = project_22_contract()
    next_contract = first.inherit_for_next_shot(first.motion.model_copy(update={"ending_pose": "small wave"}))
    assert next_contract.motion != first.motion
    assert next_contract.camera == first.camera
    assert next_contract.environment == first.environment
    assert next_contract.style == first.style


def test_prompt_compiler_is_stable_and_contains_constraints() -> None:
    contract = project_22_contract()
    image = compile_prompts(contract, generation_kind="IMAGE")
    video = compile_prompts(contract, generation_kind="VIDEO")
    assert image == compile_prompts(contract, generation_kind="IMAGE")
    assert video == compile_prompts(contract, generation_kind="VIDEO")
    assert "No scene cuts" in video["negativeConstraints"]
    assert "CHARACTER LOCK" in video["prompt"]
    assert "CAMERA LOCK" in video["prompt"]
    assert "MOTION DELTA" in video["prompt"]
    assert "http" not in video["prompt"]
    assert ":\\" not in video["prompt"]


def test_prompt_material_change_changes_hash() -> None:
    original = project_22_contract()
    changed = original.model_copy(update={"motion": original.motion.model_copy(update={"ending_pose": "turn head"})})
    assert compile_prompts(original, generation_kind="VIDEO")["promptHash"] != compile_prompts(changed, generation_kind="VIDEO")["promptHash"]
