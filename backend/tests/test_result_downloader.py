import pytest
import httpx

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
