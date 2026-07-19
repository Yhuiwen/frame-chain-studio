import asyncio
import hashlib
import ipaddress
import os
import socket
import ssl
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
    connect_url: str
    scheme: str
    host: str
    port: int | None
    validated_addresses: tuple[str, ...]
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
        connect_url=_pinned_connect_url(normalized, addresses[0]) if parsed.scheme.lower() == "http" else normalized,
        scheme=parsed.scheme.lower(),
        host=host,
        port=port,
        validated_addresses=tuple(addresses),
        path_summary=_path_summary(parsed.path),
        url_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def _pinned_connect_url(normalized_url: str, address: str) -> str:
    parsed = urlsplit(normalized_url)
    netloc = address
    if ":" in address and not address.startswith("["):
        netloc = f"[{address}]"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


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
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.config = config
        self.resolver = resolver
        self.transport = transport
        self.ssl_context = ssl_context

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
                        headers = {"Accept": "*/*", "Host": info.host}
                        if info.port is not None:
                            headers["Host"] = f"{info.host}:{info.port}"
                        if info.scheme == "https" and self.transport is None:
                            pinned = await self._request_https_pinned(info, headers=headers)
                            status_code = pinned.status_code
                            response_headers = pinned.headers
                            body_iter = pinned.iter_bytes(self.config.chunk_bytes)
                        else:
                            response = client.stream("GET", info.connect_url, headers=headers)
                            stream_context = response
                            httpx_response = await stream_context.__aenter__()
                            status_code = httpx_response.status_code
                            response_headers = dict(httpx_response.headers)
                            body_iter = httpx_response.aiter_bytes(chunk_size=self.config.chunk_bytes)
                        try:
                            if status_code in {301, 302, 303, 307, 308}:
                                if redirect_index >= self.config.max_redirects:
                                    raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Too many result URL redirects.")
                                location = response_headers.get("location")
                                if not location:
                                    raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Redirect response missing Location.")
                                current_url = urljoin(info.url, location)
                                continue
                            if status_code >= 400:
                                raise DownloadError(
                                    "DOWNLOAD_HTTP_ERROR",
                                    f"Result download failed with HTTP {status_code}.",
                                    retryable=status_code in {408, 429, 500, 502, 503, 504},
                                    details={"status_code": status_code},
                                )
                            content_length = response_headers.get("content-length")
                            if content_length and int(content_length) > self.config.max_bytes:
                                raise DownloadError("DOWNLOAD_TOO_LARGE", "Result file exceeds configured size limit.")
                            with absolute_path.open("wb") as handle:
                                async for chunk in body_iter:
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
                                mime_type=response_headers.get("content-type"),
                                file_name=None,
                            )
                        finally:
                            if info.scheme == "https" and self.transport is None:
                                pinned.close()
                            else:
                                await stream_context.__aexit__(None, None, None)
                    except httpx.TimeoutException as exc:
                        raise DownloadError("DOWNLOAD_TIMEOUT", "Result download timed out.", retryable=True) from exc
                    except httpx.HTTPError as exc:
                        raise DownloadError("DOWNLOAD_NETWORK_ERROR", "Result download network error.", retryable=True) from exc
                raise DownloadError("DOWNLOAD_REDIRECT_ERROR", "Too many result URL redirects.")
        except Exception:
            if absolute_path.exists():
                absolute_path.unlink(missing_ok=True)
            raise

    async def _request_https_pinned(self, info: SafeUrlInfo, *, headers: dict[str, str]) -> "PinnedResponse":
        last_error: Exception | None = None
        for address in info.validated_addresses:
            try:
                return await _open_https_pinned(
                    info,
                    address=address,
                    headers=headers,
                    connect_timeout=self.config.connect_timeout_seconds,
                    read_timeout=self.config.read_timeout_seconds,
                    ssl_context=self.ssl_context,
                )
            except (OSError, ssl.SSLError, asyncio.TimeoutError) as exc:
                last_error = exc
                continue
        raise DownloadError(
            "DOWNLOAD_NETWORK_ERROR",
            "Result HTTPS download failed for all validated addresses.",
            retryable=True,
        ) from last_error


class PinnedResponse:
    def __init__(
        self,
        *,
        status_code: int,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        initial_body: bytes,
        content_length: int | None,
        chunked: bool,
        read_timeout: float,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self.reader = reader
        self.writer = writer
        self.initial_body = initial_body
        self.content_length = content_length
        self.chunked = chunked
        self.read_timeout = read_timeout

    async def iter_bytes(self, chunk_size: int):
        if self.chunked:
            async for chunk in self._iter_chunked():
                yield chunk
            return
        remaining = self.content_length
        if self.initial_body:
            chunk = self.initial_body if len(self.initial_body) <= chunk_size else self.initial_body[:chunk_size]
            yield chunk
            extra = self.initial_body[len(chunk):]
            if extra:
                for offset in range(0, len(extra), chunk_size):
                    yield extra[offset : offset + chunk_size]
            if remaining is not None:
                remaining -= len(self.initial_body)
        while remaining is None or remaining > 0:
            limit = chunk_size if remaining is None else min(chunk_size, remaining)
            chunk = await asyncio.wait_for(self.reader.read(limit), timeout=self.read_timeout)
            if not chunk:
                return
            yield chunk
            if remaining is not None:
                remaining -= len(chunk)

    async def _iter_chunked(self):
        pending = self.initial_body
        while True:
            line, pending = await _read_line(self.reader, pending, self.read_timeout)
            size_text = line.split(b";", 1)[0].strip()
            size = int(size_text, 16)
            if size == 0:
                return
            chunk, pending = await _read_exact(self.reader, pending, size + 2, self.read_timeout)
            yield chunk[:-2]

    def close(self) -> None:
        self.writer.close()


async def _open_https_pinned(
    info: SafeUrlInfo,
    *,
    address: str,
    headers: dict[str, str],
    connect_timeout: float,
    read_timeout: float,
    ssl_context: ssl.SSLContext | None,
) -> PinnedResponse:
    parsed = urlsplit(info.url)
    port = info.port or 443
    context = ssl_context or ssl.create_default_context()
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host=address,
            port=port,
            ssl=context,
            server_hostname=info.host,
        ),
        timeout=connect_timeout,
    )
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    request_headers = {
        "Host": headers["Host"],
        "Accept": headers.get("Accept", "*/*"),
        "User-Agent": "frame-chain-studio-result-downloader/0.1",
        "Connection": "close",
    }
    raw = f"GET {path} HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in request_headers.items()) + "\r\n"
    writer.write(raw.encode("ascii"))
    await writer.drain()
    header_bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=read_timeout)
    head, initial_body = header_bytes.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    status_parts = lines[0].decode("iso-8859-1").split(" ", 2)
    if len(status_parts) < 2 or not status_parts[1].isdigit():
        raise DownloadError("DOWNLOAD_NETWORK_ERROR", "Invalid HTTPS response status line.", retryable=True)
    response_headers: dict[str, str] = {}
    for line in lines[1:]:
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        response_headers[key.decode("iso-8859-1").lower()] = value.strip().decode("iso-8859-1")
    transfer_encoding = response_headers.get("transfer-encoding", "").lower()
    content_length = response_headers.get("content-length")
    return PinnedResponse(
        status_code=int(status_parts[1]),
        headers=response_headers,
        reader=reader,
        writer=writer,
        initial_body=initial_body,
        content_length=int(content_length) if content_length and content_length.isdigit() else None,
        chunked="chunked" in transfer_encoding,
        read_timeout=read_timeout,
    )


async def _read_line(
    reader: asyncio.StreamReader,
    pending: bytes,
    read_timeout: float,
) -> tuple[bytes, bytes]:
    while b"\r\n" not in pending:
        pending += await asyncio.wait_for(reader.read(4096), timeout=read_timeout)
    line, pending = pending.split(b"\r\n", 1)
    return line, pending


async def _read_exact(
    reader: asyncio.StreamReader,
    pending: bytes,
    size: int,
    read_timeout: float,
) -> tuple[bytes, bytes]:
    while len(pending) < size:
        pending += await asyncio.wait_for(reader.read(size - len(pending)), timeout=read_timeout)
    return pending[:size], pending[size:]
