from io import BytesIO
from typing import Any, cast

from PIL import Image
import pytest
from sqlmodel import Session

from app.core.errors import AppError
from app.models.entities import ProviderAdapterType, ProviderModelGenerationType
from app.models.schemas import ProjectCreate, ProjectUpdate, ProviderConfigImport, ProviderConfigImportModel
from app.services import provider_management, studio


def image_bytes(fmt: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), "navy").save(output, format=fmt)
    return output.getvalue()


@pytest.mark.parametrize("conflict", ["Test", " test ", "Ｔｅｓｔ"])
def test_project_name_normalization_rejects_conflicts(session: Session, conflict: str) -> None:
    studio.create_project(session, ProjectCreate(name="test"))
    with pytest.raises(AppError) as caught:
        studio.create_project(session, ProjectCreate(name=conflict))
    assert caught.value.code == "PROJECT_NAME_CONFLICT"


def test_archive_restore_and_confirmed_delete(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Disposable"))
    studio.archive_project(session, project.id or 0)
    assert studio.list_projects(session) == []
    assert len(studio.list_projects(session, archived=True)) == 1
    with pytest.raises(AppError) as caught:
        studio.delete_project(session, project.id or 0, confirmation_name="wrong", acknowledged=True)
    assert caught.value.code == "PROJECT_DELETE_CONFIRMATION_MISMATCH"
    studio.restore_project(session, project.id or 0)
    assert studio.list_projects(session)[0].name == "Disposable"


def test_provider_import_models_and_rejects_secrets(session: Session) -> None:
    payload = ProviderConfigImport(
        display_name="Fake", provider_key="fake-import", adapter=ProviderAdapterType.FAKE,
        base_url="http://127.0.0.1:8090",
        models=[ProviderConfigImportModel(model_key="image", type=ProviderModelGenerationType.IMAGE)],
    )
    profile = provider_management.import_provider_config(session, payload)
    assert provider_management.list_provider_models(session, int(profile["id"]))[0]["generation_type"] == "IMAGE"
    with pytest.raises(AppError) as caught:
        provider_management.import_provider_config(session, payload.model_copy(update={"config": {"api_key": "never"}}))
    assert caught.value.code == "PROVIDER_CONFIG_CONTAINS_SECRET"


def test_generation_settings_validate_provider_model_pair(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Settings"))
    profile = provider_management.import_provider_config(session, ProviderConfigImport(
        display_name="Fake", provider_key="fake-settings", adapter=ProviderAdapterType.FAKE,
        base_url="http://127.0.0.1:8090",
        models=[ProviderConfigImportModel(model_key="image", type=ProviderModelGenerationType.IMAGE)],
    ))
    assert profile["provider_key"] == "fake-settings"
    studio.update_project(session, project.id or 0, ProjectUpdate(image_provider_id="fake-settings", image_model="image"))
    with pytest.raises(AppError) as caught:
        studio.update_project(session, project.id or 0, ProjectUpdate(video_provider_id="fake-settings", video_model="image"))
    assert caught.value.code == "MODEL_TYPE_MISMATCH"


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_create_character_from_decoded_image(session: Session, fmt: str, mime: str) -> None:
    project = studio.create_project(session, ProjectCreate(name=f"Characters {fmt}"))
    result = cast(dict[str, Any], studio.create_character_from_upload(session, project.id or 0, name="Mira", description="Lead", appearance="blue coat", content=image_bytes(fmt), content_type=mime))
    assert result["character"]["primary_reference_asset_id"] == result["asset"]["id"]
    assert result["asset"]["sha256"]
    with pytest.raises(AppError) as caught:
        studio.create_character_from_upload(session, project.id or 0, name="Mira", description="", appearance="", content=image_bytes(fmt), content_type=mime)
    assert caught.value.code == "CHARACTER_NAME_CONFLICT"


def test_self_rename_is_allowed(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Original"))
    updated = studio.update_project(session, project.id or 0, ProjectUpdate(name="Original"))
    assert updated.name == "Original"
