import hashlib
import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import ColumnElement, or_
from sqlmodel import Session, col, select

from app.models.entities import ProviderAssetCache
from app.services import task_service

logger = logging.getLogger(__name__)


def safe_reference_summary(value: str) -> dict[str, object]:
    parsed = urlsplit(value)
    return {
        "reference_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "path": parsed.path,
        "query_keys": sorted({key.split("=", 1)[0].lower() for key in parsed.query.split("&") if key}),
    }


def cleanup_expired_provider_asset_cache(
    session: Session,
    *,
    now: datetime,
    batch_size: int = 500,
    dry_run: bool = False,
    older_than: timedelta | None = None,
) -> int:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    current_time = task_service.db_time(now)
    total = 0
    while True:
        cleanup_condition: ColumnElement[bool] = col(ProviderAssetCache.expires_at).is_not(None) & (
            col(ProviderAssetCache.expires_at) <= current_time
        )
        if older_than is not None:
            cleanup_condition = or_(
                cleanup_condition,
                col(ProviderAssetCache.expires_at).is_(None)
                & (ProviderAssetCache.updated_at <= current_time - older_than),
            )
        statement = (
            select(ProviderAssetCache)
            .where(cleanup_condition)
            .order_by(col(ProviderAssetCache.id))
            .limit(batch_size)
        )
        batch = list(session.exec(statement).all())
        if not batch:
            return total
        total += len(batch)
        for cache in batch:
            logger.info(
                "provider asset cache cleanup cache_id=%s provider_id=%s asset_id=%s reference_kind=%s reference=%s dry_run=%s",
                cache.id,
                cache.provider_id,
                cache.asset_id,
                cache.reference_kind,
                safe_reference_summary(cache.reference_value),
                dry_run,
            )
            if not dry_run:
                session.delete(cache)
        if dry_run:
            session.rollback()
            return total
        session.commit()
