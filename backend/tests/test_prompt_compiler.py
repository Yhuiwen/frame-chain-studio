from app.domain.prompt_compiler import (
    COMPILER_VERSION,
    CharacterPromptInput,
    PromptCompileInput,
    compile_shot_prompt,
)


def test_prompt_compiler_orders_sections_and_sanitizes_values() -> None:
    result = compile_shot_prompt(
        PromptCompileInput(
            shot_title="Arrival",
            shot_prompt="  extra   prompt  ",
            shot_negative_prompt="blur",
            style_positive_prompt="watercolor",
            style_negative_prompt="low quality",
            style_rendering="soft ink",
            location_name="Station",
            summary="Hero enters",
            action="walks through steam",
            emotion="uncertain",
            composition="center frame",
            shot_size="wide",
            camera_angle="low angle",
            camera_movement="slow dolly",
            lighting="rim light",
            dialogue="hello\x00there",
            props=["ticket", "", "  lantern  "],
            reference_asset_ids=[9, 9, -1, 0],
            characters=[
                CharacterPromptInput(
                    name="Mira",
                    role="PRIMARY",
                    sort_order=1,
                    appearance="silver coat",
                    expression="focused",
                    reference_asset_ids=[3, 3],
                )
            ],
        )
    )

    assert result.compiler_version == COMPILER_VERSION
    assert result.compiled_prompt.splitlines() == [
        "Style: watercolor, soft ink",
        "Location: Station",
        "Shot: Hero enters",
        "Action: walks through steam",
        "Emotion: uncertain",
        "Composition: center frame, wide, low angle",
        "Camera Movement: slow dolly",
        "Lighting: rim light",
        "Dialogue: hello there",
        "Characters: Mira, primary, silver coat, focused",
        "Props: ticket, lantern",
        "Additional Prompt: extra prompt",
    ]
    assert result.compiled_negative_prompt == "low quality, blur"
    assert result.structured_payload["reference_asset_ids"] == [9, 3]
    assert "None" not in result.compiled_prompt


def test_prompt_compiler_is_deterministic_for_same_input() -> None:
    data = PromptCompileInput(
        shot_title="Same",
        characters=[
            CharacterPromptInput(name="Zed", role="SECONDARY", sort_order=2),
            CharacterPromptInput(name="Ana", role="PRIMARY", sort_order=1),
        ],
    )

    first = compile_shot_prompt(data)
    second = compile_shot_prompt(data)

    assert first == second
    assert "Ana, primary" in first.compiled_prompt
    assert first.compiled_prompt.index("Ana") < first.compiled_prompt.index("Zed")
