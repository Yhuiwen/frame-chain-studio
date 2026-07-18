import json
from copy import deepcopy
from typing import Any, Final

from app.core.redaction import redact_sensitive
from app.providers.exceptions import ProviderInvalidResponseError, truncate_text
from app.providers.models import ProviderResultUrl, RemoteJobStatus, ResponseMappingConfig

MISSING: Final = object()
MAX_PATH_SEGMENTS = 32
MAX_PATH_LENGTH = 256


def _segments(path: str) -> list[str]:
    if not path or len(path) > MAX_PATH_LENGTH:
        raise ProviderInvalidResponseError("Invalid or too-long mapping path.")
    parts = path.split(".")
    if len(parts) > MAX_PATH_SEGMENTS or any(part == "" for part in parts):
        raise ProviderInvalidResponseError("Invalid mapping path.")
    if any(any(char in part for char in "[](){}$*?`'\"") for part in parts):
        raise ProviderInvalidResponseError("Unsafe mapping path.")
    return parts


def get_by_path(data: Any, path: str, default: Any = MISSING) -> Any:
    try:
        parts = _segments(path)
    except ProviderInvalidResponseError:
        if default is MISSING:
            raise
        return default
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                if default is MISSING:
                    raise ProviderInvalidResponseError(f"Path segment '{part}' is not a list index.")
                return default
            index = int(part)
            if index >= len(current):
                return default
            current = current[index]
            continue
        return default
    return current


def require_by_path(data: Any, path: str) -> Any:
    value = get_by_path(data, path, MISSING)
    if value is MISSING:
        raise ProviderInvalidResponseError(f"Required response path '{path}' is missing.")
    return value


def set_by_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = _segments(path)
    current = data
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            child: dict[str, Any] = {}
            current[part] = child
            current = child
            continue
        if not isinstance(existing, dict):
            raise ProviderInvalidResponseError(f"Target mapping path '{path}' conflicts with existing value.")
        current = existing
    leaf = parts[-1]
    if leaf in current and isinstance(current[leaf], dict):
        raise ProviderInvalidResponseError(f"Target mapping path '{path}' conflicts with existing object.")
    current[leaf] = value


def apply_request_mapping(
    source: dict[str, Any],
    field_mapping: dict[str, str],
    fixed_fields: dict[str, Any] | None = None,
    *,
    skip_none: bool = True,
) -> dict[str, Any]:
    original = deepcopy(source)
    target: dict[str, Any] = {}
    for source_path, target_path in field_mapping.items():
        value = get_by_path(original, source_path, MISSING)
        if value is MISSING or (value is None and skip_none):
            continue
        set_by_path(target, target_path, deepcopy(value))
    for target_path, value in (fixed_fields or {}).items():
        if value is None and skip_none:
            continue
        set_by_path(target, target_path, deepcopy(value))
    return target


def normalize_remote_status(value: Any, config: ResponseMappingConfig) -> RemoteJobStatus:
    if value is None:
        return RemoteJobStatus.UNKNOWN
    for normalized, aliases in config.status_aliases.items():
        for alias in aliases:
            if isinstance(value, str) and isinstance(alias, str) and value.lower() == alias.lower():
                return RemoteJobStatus(normalized.upper())
            if isinstance(value, int) and value == alias:
                return RemoteJobStatus(normalized.upper())
            if isinstance(value, str) and not isinstance(alias, str) and value == str(alias):
                return RemoteJobStatus(normalized.upper())
    return RemoteJobStatus.UNKNOWN


def extract_result_urls(raw: Any, config: ResponseMappingConfig) -> list[ProviderResultUrl]:
    if not config.result_urls_path:
        return []
    paths = [config.result_urls_path] if isinstance(config.result_urls_path, str) else config.result_urls_path
    value = None
    for path in paths:
        value = get_by_path(raw, path, None)
        if value not in (None, ""):
            break
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [ProviderResultUrl(url=value)]
    if not isinstance(value, list):
        return []
    urls: list[ProviderResultUrl] = []
    for item in value:
        if isinstance(item, str):
            urls.append(ProviderResultUrl(url=item))
            continue
        if isinstance(item, dict):
            for path in config.result_url_item_paths:
                url = get_by_path(item, path, None)
                if isinstance(url, str) and url:
                    urls.append(
                        ProviderResultUrl(
                            url=url,
                            mime_type=item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
                            output_type=item.get("type") if isinstance(item.get("type"), str) else None,
                        )
                    )
                    break
    return urls


def summarize_response(raw: Any, max_chars: int = 4000) -> str:
    sanitized = redact_sensitive(raw)
    try:
        text = json.dumps(sanitized, ensure_ascii=True, sort_keys=True)
    except TypeError:
        text = str(sanitized)
    return truncate_text(text, max_chars)
