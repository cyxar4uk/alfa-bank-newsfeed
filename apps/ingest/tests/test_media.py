"""Картинки и полный текст: из RSS, со страницы материала; заглушки сайтов не берём."""

import httpx
import pytest

from ingest.news import media
from ingest.news.article import container_html, extract_article, html_paragraphs, usable_image
from ingest.news.fetch import Feed, entry_image, load_feeds, parse_feed
from ingest.news.media import fetch_pages
from ingest.news.normalize import normalize

LONG = "Совет директоров Банка России принял решение сохранить ключевую ставку на уровне 14% годовых."


def rss(item: str, ns: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/" {ns}>
<channel><title>t</title>{item}</channel></rss>""".encode()


def item(extra: str = "", summary: str = "Лид") -> str:
    return f"""<item><title>Ставка сохранена</title><link>https://site.ru/news/1</link>
<description><![CDATA[{summary}]]></description>{extra}</item>"""


FEED = Feed("t", "Издатель", "https://site.ru/rss", icon="https://site.ru/icon.png")


@pytest.mark.parametrize(
    "extra, summary, expected",
    [
        ('<media:content url="https://img.site.ru/a.jpg" medium="image"/>', "Лид", "https://img.site.ru/a.jpg"),
        ('<media:thumbnail url="https://img.site.ru/t.jpg"/>', "Лид", "https://img.site.ru/t.jpg"),
        (
            '<enclosure url="https://img.site.ru/e.jpg" type="image/jpeg" length="1"/>',
            "Лид",
            "https://img.site.ru/e.jpg",
        ),
        ("", '<img src="/cdn/image_icon.jpg"> Лид', "https://site.ru/cdn/image_icon.jpg"),
        ('<enclosure url="https://site.ru/a.mp3" type="audio/mpeg" length="1"/>', "Лид", None),
        ('<media:content url="https://site.ru/images/logo.png" medium="image"/>', "Лид", None),
    ],
)
def test_image_from_rss(extra, summary, expected):
    [raw] = parse_feed(FEED, rss(item(extra, summary)))
    assert raw.image == expected
    src = normalize(raw)
    assert src.image_url == expected and src.source_icon_url == "https://site.ru/icon.png"


def test_full_text_from_rss_only_where_feed_allows_it():
    body = f"<content:encoded><![CDATA[<p>{LONG}</p><p>Коротко.</p><script>x()</script>]]></content:encoded>"
    [closed] = parse_feed(FEED, rss(item(body)))
    assert closed.text is None and normalize(closed).text is None
    [open_] = parse_feed(Feed("t", "Издатель", "https://site.ru/rss", full_text="rss"), rss(item(body)))
    assert open_.text == f"{LONG}\nКоротко." and normalize(open_).text == open_.text


def test_unknown_full_text_mode_is_rejected(tmp_path):
    path = tmp_path / "f.toml"
    path.write_text('[[feed]]\nid = "x"\npublisher = "X"\nurl = "https://x.ru"\nfull_text = "scrape"\n', "utf-8")
    with pytest.raises(ValueError, match="full_text"):
        load_feeds(str(path))


def test_full_text_only_for_feeds_whose_terms_allow_it():
    feeds = load_feeds()
    assert {f.id for f in feeds if f.full_text} == {"cbr-press", "cbr-events", "government", "nalog", "forbes"}
    assert all(f.icon.startswith(("https://", "http://")) for f in feeds if f.enabled)


def test_counter_pixel_is_not_an_image():
    summary = '<img src="https://mc.yandex.ru/watch/1" width="1" height="1"><img src="/photo.jpg"> Лид'
    [raw] = parse_feed(FEED, rss(item("", summary)))
    assert raw.image == "https://site.ru/photo.jpg"


def test_rss_full_text_starts_with_author():
    body = f"<author>Иван Петров</author><content:encoded><![CDATA[<p>{LONG}</p>]]></content:encoded>"
    [raw] = parse_feed(Feed("t", "Издатель", "https://site.ru/rss", full_text="rss"), rss(item(body)))
    assert raw.text == f"Автор: Иван Петров\n{LONG}"


def test_entry_image_ignores_non_http():
    assert entry_image({"media_thumbnail": [{"url": "data:image/png;base64,AAA"}]}) is None


def test_usable_image_drops_site_placeholders():
    assert usable_image("https://cdn.iz.ru/sites/default/files/styles/900x506/public/x.jpg")
    assert usable_image("https://x.ru/i/ecologo.jpg") and usable_image("https://x.ru/i/default-rossii.jpg")
    assert usable_image("https://www.cbr.ru/common/images/share-1.jpg") is None
    assert usable_image("https://rg.ru/i/rg-social-dummy-logo.png") is None
    assert usable_image("https://cdn.site.ru/2026/10/photo.jpg") == "https://cdn.site.ru/2026/10/photo.jpg"


PAGE = f"""<html><head><meta property="og:image" content="/img/photo.jpg"></head><body>
<div class="calendar">{LONG.replace("ставку", "календарь")} меню меню меню меню</div>
<div class="reader_article_body extra"><div class="lead"><p>{LONG}</p></div><p>{LONG} Второй абзац.</p></div>
<div class="reader_article_body_footer"><p>{LONG} Подвал.</p></div>
</body></html>"""


def test_container_matches_whole_class_and_nested_tags():
    inner = container_html(PAGE, "reader_article_body")
    assert inner.startswith('<div class="reader_article_body extra">') and "Второй абзац" in inner
    assert "Подвал" not in inner
    assert container_html(PAGE, "article_body") is None


def test_article_with_container_and_image():
    a = extract_article(PAGE, "https://government.ru/news/1/", "reader_article_body")
    assert a.body == f"{LONG}\n{LONG} Второй абзац." and a.image == "https://government.ru/img/photo.jpg"
    assert html_paragraphs("<p>Раз</p><p>Два</p>") == "Раз\nДва"


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_page_media_takes_text_only_when_asked():
    c = client(lambda r: httpx.Response(200, html=PAGE))
    job = media.PageJob("1", "https://government.ru/news/1/", want_text=False, container="reader_article_body")
    assert media.page_media(c, job) == media.PageMedia(image="https://government.ru/img/photo.jpg", text=None)
    with_text = media.page_media(c, media.PageJob("1", job.url, True, "reader_article_body"))
    assert with_text.text.endswith("Второй абзац.")


def test_page_media_skips_non_html_and_large_pages(monkeypatch):
    pdf = client(lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}))
    assert media.page_media(pdf, media.PageJob("1", "https://x.ru/a.pdf", True)) == media.PageMedia()
    monkeypatch.setattr(media, "MAX_PAGE_BYTES", 100)
    big = client(lambda r: httpx.Response(200, html=PAGE))
    assert media.page_media(big, media.PageJob("1", "https://x.ru/a", True)) == media.PageMedia()


def test_unreachable_pages_are_left_for_next_round(monkeypatch):
    def handler(request):
        if "down" in str(request.url):
            raise httpx.ConnectError("нет сети")
        if "gone" in str(request.url):
            return httpx.Response(404, html="нет")
        return httpx.Response(200, html=PAGE)

    real = httpx.Client
    monkeypatch.setattr(media.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    jobs = [media.PageJob("ok", "https://x.ru/ok", False), media.PageJob("down", "https://x.ru/down", False),
            media.PageJob("gone", "https://x.ru/gone", False)]  # fmt: skip
    got = fetch_pages(jobs)  # настоящая функция: conftest подменяет её только в модуле media
    assert set(got) == {"ok", "gone"} and got["gone"] == media.PageMedia()
    assert got["ok"].image == "https://x.ru/img/photo.jpg"


def test_url_variants_cover_http_only_sites_and_trailing_slash():
    assert media.url_variants("https://government.ru/news/1") == [
        "https://government.ru/news/1",
        "https://government.ru/news/1/",
        "http://government.ru/news/1",
        "http://government.ru/news/1/",
    ]
    assert media.url_variants("https://x.ru/a?id=1") == ["https://x.ru/a?id=1", "http://x.ru/a?id=1"]


def test_busy_site_is_retried_and_relative_image_follows_real_address(monkeypatch):
    def handler(request):
        if "busy" in str(request.url):
            return httpx.Response(503)
        if request.url.scheme == "https":
            raise httpx.ConnectError("https не отвечает")
        return httpx.Response(200, html=PAGE)

    real = httpx.Client
    monkeypatch.setattr(media.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    got = fetch_pages([media.PageJob("gov", "https://government.ru/news/1", False),
                       media.PageJob("busy", "https://x.ru/busy", False)])  # fmt: skip
    assert set(got) == {"gov"} and got["gov"].image == "http://government.ru/img/photo.jpg"
