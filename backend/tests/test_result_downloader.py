import asyncio
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.media.result_downloader import DownloadConfig, DownloadError, ResultDownloader, UrlSafetyConfig, safe_url_info


def resolver(host: str, _port: int | None) -> list[str]:
    return {
        "example.com": ["93.184.216.34"],
        "private.test": ["127.0.0.1"],
        "mixed.test": ["93.184.216.34", "10.0.0.5"],
    }.get(host, ["93.184.216.34"])


def test_url_safety_accepts_public_http_and_rejects_dangerous_urls() -> None:
    info = safe_url_info("https://example.com/result.png?token=secret", resolver=resolver)
    assert info.host == "example.com"
    assert "token" not in info.path_summary

    rejected = [
        "file:///tmp/a.png",
        "ftp://example.com/a.png",
        "data:text/plain,nope",
        "https://user:pass@example.com/a.png",
        "https://example.com/a.png#frag",
        "http://127.0.0.1/a.png",
        "http://[::1]/a.png",
        "http://mixed.test/a.png",
    ]
    for url in rejected:
        with pytest.raises(DownloadError):
            safe_url_info(url, resolver=resolver)


def test_private_allowlist_only_applies_in_development_or_test() -> None:
    config = UrlSafetyConfig(env="test", allowed_private_hosts={"private.test"})
    assert safe_url_info("http://private.test/result.png", resolver=resolver, config=config).host == "private.test"

    prod_config = UrlSafetyConfig(env="production", allowed_private_hosts={"private.test"})
    with pytest.raises(DownloadError):
        safe_url_info("http://private.test/result.png", resolver=resolver, config=prod_config)


@pytest.mark.anyio
async def test_stream_download_limits_size_and_omits_credentials(tmp_path) -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return httpx.Response(200, content=b"abc", headers={"content-length": "3", "content-type": "image/png"})

    downloader = ResultDownloader(
        DownloadConfig(
            storage_dir=tmp_path,
            max_bytes=8,
            url_safety=UrlSafetyConfig(env="test"),
        ),
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    downloaded = await downloader.download("https://example.com/result.png?secret=1", result_id=1)

    assert downloaded.file_size == 3
    assert downloaded.absolute_path.exists()
    assert "authorization" not in seen_headers
    assert "cookie" not in seen_headers
    assert downloaded.relative_path.endswith(".part")


@pytest.mark.anyio
async def test_download_revalidates_redirect_and_blocks_private_target(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://private.test/result.png"})

    downloader = ResultDownloader(
        DownloadConfig(
            storage_dir=tmp_path,
            max_redirects=3,
            url_safety=UrlSafetyConfig(env="production"),
        ),
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DownloadError) as exc:
        await downloader.download("https://example.com/redirect", result_id=2)
    assert exc.value.code == "DOWNLOAD_URL_REJECTED"


@pytest.mark.anyio
async def test_download_rejects_content_length_and_actual_size_over_limit(tmp_path) -> None:
    downloader = ResultDownloader(
        DownloadConfig(storage_dir=tmp_path, max_bytes=2, url_safety=UrlSafetyConfig(env="test")),
        resolver=resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"abc", headers={"content-type": "image/png"})
        ),
    )

    with pytest.raises(DownloadError) as exc:
        await downloader.download("https://example.com/large.png", result_id=3)
    assert exc.value.code == "DOWNLOAD_TOO_LARGE"
    assert not list((tmp_path / "temp" / "results").glob("*.part"))


def _generate_cert(tmp_path: Path, *, hostname: str) -> tuple[Path, Path]:
    cert = tmp_path / f"{hostname}.crt"
    key = tmp_path / f"{hostname}.key"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    key.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return cert, key


@pytest.mark.anyio
async def test_https_download_uses_validated_ip_with_original_sni_and_host(tmp_path: Path) -> None:
    hostname = "pinned.test"
    cert, key = _generate_cert(tmp_path, hostname=hostname)
    observed: dict[str, Any] = {"requests": 0}
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=cert, keyfile=key)

    def sni_callback(_ssl_object: object, server_name: str | None, _context: object) -> None:
        observed["sni"] = server_name

    server_context.set_servername_callback(sni_callback)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        observed["requests"] = int(observed["requests"]) + 1
        request = await reader.readuntil(b"\r\n\r\n")
        observed["raw_request"] = request.decode("iso-8859-1")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Type: image/png\r\nConnection: close\r\n\r\nabc"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    client_context = ssl.create_default_context(cafile=str(cert))
    resolver_calls = 0

    def pinned_resolver(host: str, _port: int | None) -> list[str]:
        nonlocal resolver_calls
        resolver_calls += 1
        assert host == hostname
        return ["127.0.0.1"]

    try:
        downloader = ResultDownloader(
            DownloadConfig(
                storage_dir=tmp_path,
                url_safety=UrlSafetyConfig(env="test", allowed_private_hosts={hostname}),
            ),
            resolver=pinned_resolver,
            ssl_context=client_context,
        )

        downloaded = await downloader.download(f"https://{hostname}:{port}/result.png", result_id=20)
    finally:
        server.close()
        await server.wait_closed()

    assert downloaded.file_size == 3
    assert observed["requests"] == 1
    assert observed["sni"] == hostname
    assert f"Host: {hostname}:{port}" in str(observed["raw_request"])
    assert resolver_calls == 1


@pytest.mark.anyio
async def test_https_hostname_verification_uses_original_host_not_pinned_ip(tmp_path: Path) -> None:
    cert, key = _generate_cert(tmp_path, hostname="other.test")
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=cert, keyfile=key)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nabc")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    client_context = ssl.create_default_context(cafile=str(cert))
    try:
        downloader = ResultDownloader(
            DownloadConfig(
                storage_dir=tmp_path,
                url_safety=UrlSafetyConfig(env="test", allowed_private_hosts={"pinned.test"}),
            ),
            resolver=lambda _host, _port: ["127.0.0.1"],
            ssl_context=client_context,
        )
        with pytest.raises(DownloadError):
            await downloader.download(f"https://pinned.test:{port}/result.png", result_id=21)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
async def test_https_download_supports_ipv6_pinned_connection(tmp_path: Path) -> None:
    hostname = "ipv6-pinned.test"
    cert, key = _generate_cert(tmp_path, hostname=hostname)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=cert, keyfile=key)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Type: image/png\r\n\r\nabc")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    try:
        server = await asyncio.start_server(handle, "::1", 0, ssl=server_context)
    except OSError:
        pytest.skip("IPv6 loopback is not available on this platform")
    port = server.sockets[0].getsockname()[1]
    try:
        downloader = ResultDownloader(
            DownloadConfig(
                storage_dir=tmp_path,
                url_safety=UrlSafetyConfig(env="test", allowed_private_hosts={hostname}),
            ),
            resolver=lambda _host, _port: ["::1"],
            ssl_context=ssl.create_default_context(cafile=str(cert)),
        )

        downloaded = await downloader.download(f"https://{hostname}:{port}/result.png", result_id=22)
    finally:
        server.close()
        await server.wait_closed()

    assert downloaded.file_size == 3
