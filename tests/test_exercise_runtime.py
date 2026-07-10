from __future__ import annotations

import pytest

from scripts.exercise_runtime import NoRedirectHandler, normalize_base_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/runtime.json",
        "ftp://example.com/runtime",
        "https://user:password@example.com",
        "not-a-url",
    ],
)
def test_normalize_base_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_base_url(url, has_operator_token=False)


def test_operator_token_requires_https_off_loopback() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://example.com", has_operator_token=True)

    assert normalize_base_url("http://127.0.0.1:8000/", True) == "http://127.0.0.1:8000"
    assert normalize_base_url("https://example.com/", True) == "https://example.com"


def test_redirect_handler_never_forwards_requests() -> None:
    handler = NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://example.com") is None
