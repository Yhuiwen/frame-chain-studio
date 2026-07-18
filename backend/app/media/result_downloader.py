import asyncio
import hashlib
import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from app.core.redaction import redact_sensitive


class DownloadError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.details = redact_sensitive(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class UrlSafetyConfig:
    env: str = "development"
    allowed_private_hosts: set[str] | None = None
    max_url_length: int = 4096


@dataclass(frozen=True)
class DownloadConfig:
    storage_dir: Path
    connect_timeout_seconds: float = 10
    read_timeout_seconds: float = 60
    total_timeout_seconds: float = 900
    max_bytes: int = 50 * 1024 * 1024
    chunk_bytes: int = 1024 * 1024
    max_redirects: int = 3
    url_safety: UrlSafetyConfig = UrlSafetyConfig()


@dataclass(frozen=True)
class SafeUrlInfo:
    url: str
    scheme: str
    host: str
    port: int | None
    path_summary: str
    url_hash: str


@dataclass(frozen=True)
class DownloadedFile:
    absolute_path: Path
    relative_path: str
    file_size: int
    sha256: str
    mime_type: str | None
    file_name: str | None


Resolver = Callable[[str, int | None], list[str]]


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not parsed.path:
        path = "/"
    else:
        path = parsed.path
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def safe_url_info(url: str, *, resolver: Resolver | None = None, config: UrlSafetyConfig | None = None) -> SafeUrlInfo:
    resolved_config = config or UrlSafetyConfig()
    if len(url) > resolved_config.max_url_length:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL is too long.", details={"reason": "too_long"})
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL scheme is not allowed.", details={"scheme": parsed.scheme})
    if parsed.username or parsed.password:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL must not include credentials.")
    if parsed.fragment:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL must not include a fragment.")
    if not parsed.hostname:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL host is required.")
    try:
        parsed.port
    except ValueError as exc:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL port is invalid.") from exc
    host = parsed.hostname.lower()
    port = parsed.port
    addresses = _resolve_host(host, port, resolver=resolver)
    allowed_private = resolved_config.allowed_private_hosts or set()
    for address in addresses:
        if _ip_is_forbidden(address) and not _host_is_allowed_private(host, address, resolved_config.env, allowed_private):
            raise DownloadError(
                "DOWNLOAD_URL_REJECTED",
                "Result URL resolves to a forbidden address.",
                details={"host": host, "address": address},
            )
    normalized = normalize_url(url)
    return SafeUrlInfo(
        url=normalized,
        scheme=parsed.scheme.lower(),
        host=host,
        port=port,
        path_summary=_path_summary(parsed.path),
        url_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def _resolve_host(host: str, port: int | None, *, resolver: Resolver | None = None) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    if resolver is not None:
        return resolver(host, port)
    try:
        infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DownloadError("DOWNLOAD_URL_REJECTED", "Result URL host could not be resolved.") from exc
    return sorted({item[4][0] for item in infos})


def _host_is_allowed_private(host: str, address: str, env: str, allowed_private: set[str]) -> bool:
    if env not in {"development", "test"}:
        return False
    return host.lower() in allowed_private or address.lower() in allowed_private


def _ip_is_forbidden(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    blocked_networks = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]
    return (
        any(ip in network for network in blocked_networks)
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _path_summary(path: str) -> str:
    if not path:
        return "/"
    name = Path(path).name
    if len(name) > 80:
        name = name[:77] + "..."
    return f"/.../{name}" if path.count("/") > 1 else path


class ResultDownloader:
    def __init__(
        self,
        config: DownloadConfig,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.resolver = resolver
        self.transport = transport

    async def download(self, url: str, *, result_id: int) -> DownloadedFile:
        start = asyncio.get_running_loop().time()
        current_url = url
        seen: set[str] = set()
        previous_scheme: str | None = None
        temp_root = self.config.storage_dir / "temp" / "results"
        temp_root.mkdir(parents=True, exist_ok=True)
        relative_path = Path("temp") / "results" / f"result-{result_id}-{uuid4().hex}.part"
        absolute_path = self.config.storage_dir / relative_path
        sha256 = hashlib.sha256()
        size = 0
        try:
            timeout = httpx.Timeout(
                connect=self.config.connect_timeout_seconds,
                read=self.config.read_timeout_seconds,
                write=self.config.read_timeout_seconds,
                pool=self.config.connect_timeout_seconds,
            )
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                for redirect_index in range(self.config.max_redirects + 1):
                    info = safe_url_info(
                        current_url,
                        resolver=self.resolver,
                        config=self.config.url_safety,
                    )
                    if info.url in seen:
                        raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Result URL redirect loop detected.")
                    seen.add(info.url)
                    if previous_scheme == "https" and info.scheme == "http":
                        raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "HTTPS to HTTP result redirect is not allowed.")
                    previous_scheme = info.scheme
                    try:
                        async with client.stream("GET", info.url, headers={"Accept": "*/*"}) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                if redirect_index >= self.config.max_redirects:
                                    raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Too many result URL redirects.")
                                location = response.headers.get("location")
                                if not location:
                                    raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Redirect response missing Location.")
                                current_url = urljoin(info.url, location)
                                continue
                            if response.status_code >= 400:
                                raise DownloadError(
                                    "DOWNLOAD_HTTP_ERROR",
                                    f"Result download failed with HTTP {response.status_code}.",
                                    retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                                    details={"status_code": response.status_code},
                                )
                            content_length = response.headers.get("content-length")
                            if content_length and int(content_length) > self.config.max_bytes:
                                raise DownloadError("DOWNLOAD_TOO_LARGE", "Result file exceeds configured size limit.")
                            with absolute_path.open("wb") as handle:
                                async for chunk in response.aiter_bytes(chunk_size=self.config.chunk_bytes):
                                    if asyncio.get_running_loop().time() - start > self.config.total_timeout_seconds:
                                        raise DownloadError("DOWNLOAD_TIMEOUT", "Result download exceeded total timeout.", retryable=True)
                                    if not chunk:
                                        continue
                                    size += len(chunk)
                                    if size > self.config.max_bytes:
                                        raise DownloadError("DOWNLOAD_TOO_LARGE", "Result file exceeds configured size limit.")
                                    handle.write(chunk)
                                    sha256.update(chunk)
                                handle.flush()
                                os.fsync(handle.fileno())
                            if size == 0:
                                raise DownloadError("DOWNLOAD_INCOMPLETE", "Result download produced an empty file.")
                            return DownloadedFile(
                                absolute_path=absolute_path,
                                relative_path=relative_path.as_posix(),
                                file_size=size,
                                sha256=sha256.hexdigest(),
                                mime_type=response.headers.get("content-type"),
                                file_name=None,
                            )
                    except httpx.TimeoutException as exc:
                        raise DownloadError("DOWNLOAD_TIMEOUT", "Result download timed out.", retryable=True) from exc
                    except httpx.HTTPError as exc:
                        raise DownloadError("DOWNLOAD_NETWORK_ERROR", "Result download network error.", retryable=True) from exc
                raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Too many result URL redirects.")
        except Exception:
            if absolute_path.exists():
                absolute_path.unlink(missing_ok=True)
            raise
