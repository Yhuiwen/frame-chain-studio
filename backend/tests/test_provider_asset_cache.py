from datetime import timedelta

from sqlmodel import Session, select

from app.models.entities import Asset, AssetType, ProviderAssetCache, utcnow
from app.models.schemas import ProjectCreate, ShotCreate
from app.services import studio
from app.services.provider_asset_cache import cleanup_expired_provider_asset_cache


SECRET_URL = "https://uploads.example.test/file.png?token=TOP_SECRET_UPLOAD_TOKEN&X-Amz-Signature=VERY_SECRET_SIGNATURE"


def _cache(session: Session, *, asset_id: int, expires_delta: timedelta | None, updated_delta: timedelta | None = None) -> ProviderAssetCache:
    now = utcnow().replace(tzinfo=None)
    cache = ProviderAssetCache(
        provider_id="remote",
        asset_id=asset_id,
        asset_sha256=f"sha-{asset_id}-{expires_delta}-{updated_delta}",
        reference_kind="url",
        reference_value=SECRET_URL,
        expires_at=now + expires_delta if expires_delta is not None else None,
        updated_at=now - (updated_delta or timedelta()),
    )
    session.add(cache)
    session.commit()
    session.refresh(cache)
    return cache


def _project_shot_asset(session: Session) -> tuple[int, int, int]:
    project = studio.create_project(session, ProjectCreate(name="Cache"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot"))
    asset = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.KEYFRAME,
        path="/tmp/nonexistent.png",
        mime_type="image/png",
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return project.id or 0, shot.id or 0, asset.id or 0


def test_cleanup_deletes_expired_keeps_fresh_and_non_expiring(session: Session) -> None:
    _, _, asset_id = _project_shot_asset(session)
    expired = _cache(session, asset_id=asset_id, expires_delta=timedelta(seconds=-1))
    fresh = _cache(session, asset_id=asset_id, expires_delta=timedelta(hours=1))
    forever = _cache(session, asset_id=asset_id, expires_delta=None)

    deleted = cleanup_expired_provider_asset_cache(session, now=utcnow(), batch_size=500)

    assert deleted == 1
    remaining = {cache.id for cache in session.exec(select(ProviderAssetCache)).all()}
    assert expired.id not in remaining
    assert fresh.id in remaining
    assert forever.id in remaining


def test_cleanup_dry_run_and_batch_size(session: Session) -> None:
    _, _, asset_id = _project_shot_asset(session)
    _cache(session, asset_id=asset_id, expires_delta=timedelta(seconds=-2))
    _cache(session, asset_id=asset_id, expires_delta=timedelta(seconds=-1))

    assert cleanup_expired_provider_asset_cache(session, now=utcnow(), batch_size=1, dry_run=True) == 1
    assert len(session.exec(select(ProviderAssetCache)).all()) == 2
    assert cleanup_expired_provider_asset_cache(session, now=utcnow(), batch_size=1) == 2
    assert session.exec(select(ProviderAssetCache)).all() == []


def test_cleanup_older_than_can_delete_non_expiring_rows(session: Session) -> None:
    _, _, asset_id = _project_shot_asset(session)
    old = _cache(session, asset_id=asset_id, expires_delta=None, updated_delta=timedelta(days=3))
    recent = _cache(session, asset_id=asset_id, expires_delta=None, updated_delta=timedelta(hours=1))

    deleted = cleanup_expired_provider_asset_cache(
        session,
        now=utcnow(),
        batch_size=500,
        older_than=timedelta(days=1),
    )

    remaining = {cache.id for cache in session.exec(select(ProviderAssetCache)).all()}
    assert deleted == 1
    assert old.id not in remaining
    assert recent.id in remaining


def test_cleanup_log_and_repr_do_not_expose_reference_secret(
    session: Session,
    monkeypatch,
) -> None:
    _, _, asset_id = _project_shot_asset(session)
    cache = _cache(session, asset_id=asset_id, expires_delta=timedelta(seconds=-1))
    assert "TOP_SECRET_UPLOAD_TOKEN" not in repr(cache)
    assert "VERY_SECRET_SIGNATURE" not in repr(cache)

    captured: list[str] = []

    def capture_info(message: str, *args: object, **_kwargs: object) -> None:
        captured.append(message % args)

    monkeypatch.setattr("app.services.provider_asset_cache.logger.info", capture_info)
    cleanup_expired_provider_asset_cache(session, now=utcnow(), batch_size=500)

    logs = "\n".join(captured)
    assert "TOP_SECRET_UPLOAD_TOKEN" not in logs
    assert "VERY_SECRET_SIGNATURE" not in logs
    assert "uploads.example.test" in logs


def test_delete_asset_owner_cleans_provider_cache(session: Session) -> None:
    _, shot_id, asset_id = _project_shot_asset(session)
    _cache(session, asset_id=asset_id, expires_delta=timedelta(hours=1))

    studio.delete_shot(session, shot_id)

    assert session.exec(select(ProviderAssetCache)).all() == []


def test_delete_project_cleans_provider_cache(session: Session) -> None:
    project_id, _, asset_id = _project_shot_asset(session)
    _cache(session, asset_id=asset_id, expires_delta=timedelta(hours=1))

    studio.delete_project(session, project_id)

    assert session.exec(select(ProviderAssetCache)).all() == []
