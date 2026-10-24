from pathlib import Path

import httpx
import pytest

import api.images as images
from api.images import MAX_BYTES, ImageError, fetch, is_allowed, proxied

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
KOMMERSANT = "https://im2.kommersant.ru/Issues.photo2/x.jpg"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    # без сети: любой хост «разрешается» в публичный адрес; внутренние — в тестах явно
    monkeypatch.setattr(
        images.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", ("93.184.216.34", 0))]
    )


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_only_publisher_hosts_and_their_subdomains():
    assert is_allowed(KOMMERSANT)  # поддомен www.kommersant.ru из лент
    assert is_allowed("https://www.cbr.ru/favicon.ico")
    assert not is_allowed("https://evil.example.com/x.jpg")
    assert not is_allowed("http://127.0.0.1/x.jpg")
    assert not is_allowed("file:///etc/passwd")
    assert not is_allowed("https://user:pass@im2.kommersant.ru/x.jpg")
    assert not is_allowed("https://kommersant.ru.evil.com/x.jpg")
    assert proxied(KOMMERSANT) == "/api/img?u=https%3A%2F%2Fim2.kommersant.ru%2FIssues.photo2%2Fx.jpg"
    assert proxied("https://evil.example.com/x.jpg") == "https://evil.example.com/x.jpg"
    assert proxied(None) is None


def test_fetch_and_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    assert fetch(KOMMERSANT, tmp_path, client(handler)) == (PNG, "image/png")
    assert fetch(KOMMERSANT, tmp_path, client(handler)) == (PNG, "image/png")
    assert len(calls) == 1  # второй раз — с диска


def test_internal_address_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(images.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", ("10.0.0.5", 0))])
    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, client(lambda r: httpx.Response(200, content=PNG)))
    assert err.value.status == 403


def test_redirect_only_to_allowed_host(tmp_path):
    def handler(request):
        if request.url.host == "im2.kommersant.ru":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, client(handler))
    assert err.value.status == 403

    def good(request):
        if request.url.path == "/Issues.photo2/x.jpg":
            return httpx.Response(301, headers={"location": "/Issues.photo2/y.jpg"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    assert fetch(KOMMERSANT, tmp_path, client(good))[1] == "image/png"


def test_not_image_svg_or_too_big(tmp_path):
    html = client(lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, html)
    assert err.value.status == 415
    svg = client(lambda r: httpx.Response(200, content=b"<svg/>", headers={"content-type": "image/svg+xml"}))
    with pytest.raises(ImageError):
        fetch(KOMMERSANT, tmp_path, svg)
    big = client(
        lambda r: httpx.Response(200, content=b"0" * (MAX_BYTES + 1), headers={"content-type": "image/jpeg"})
    )
    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, big)
    assert err.value.status == 413
    assert not list(tmp_path.iterdir())  # ошибки не кэшируются


def test_endpoint(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import api.main as main

    monkeypatch.setattr(main, "fetch_image", lambda u, d: (PNG, "image/png"))
    response = TestClient(main.app).get("/api/img", params={"u": KOMMERSANT})
    assert response.status_code == 200 and response.content == PNG
    assert response.headers["x-content-type-options"] == "nosniff"

    def refuse(u, d):
        raise ImageError(403, "хост картинки не из каталога источников")

    monkeypatch.setattr(main, "fetch_image", refuse)
    assert TestClient(main.app).get("/api/img", params={"u": "https://evil.example.com/x"}).status_code == 403


def test_broken_or_odd_urls_do_not_crash():
    assert proxied("http://[::1/x") == "http://[::1/x"  # битая ссылка — как есть, без 500
    assert not is_allowed("https://im2.kommersant.ru:99999/x.jpg")
    assert not is_allowed("https://im2.kommersant.ru:8080/x.jpg")
    with pytest.raises(ImageError) as err:
        fetch("http://[::1/x", Path("."))
    assert err.value.status == 403


def test_mixed_dns_and_internal_second_hop(tmp_path, monkeypatch):
    answers = {"im2.kommersant.ru": ["93.184.216.34", "::ffff:127.0.0.1"]}
    monkeypatch.setattr(
        images.socket, "getaddrinfo", lambda host, port: [(0, 0, 0, "", (ip, 0)) for ip in answers[host]]
    )
    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, client(lambda r: httpx.Response(200, content=PNG)))
    assert err.value.status == 403  # хоть один внутренний адрес — отказ
    answers.update({"im2.kommersant.ru": ["93.184.216.34"], "www.kommersant.ru": ["10.1.2.3"]})

    def handler(request):
        if request.url.host == "im2.kommersant.ru":
            return httpx.Response(302, headers={"location": "https://www.kommersant.ru/x.jpg"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, client(handler))
    assert err.value.status == 403  # разрешённый хост, но внутренний адрес на втором шаге


def test_network_error_is_502_and_cache_is_capped(tmp_path, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("нет связи")

    with pytest.raises(ImageError) as err:
        fetch(KOMMERSANT, tmp_path, client(boom))
    assert err.value.status == 502
    monkeypatch.setattr(images, "CACHE_FILES", 2)
    ok = client(lambda r: httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    for n in range(4):
        fetch(f"https://im2.kommersant.ru/{n}.jpg", tmp_path, ok)
    assert len(list(tmp_path.glob("*.bin"))) == 2
