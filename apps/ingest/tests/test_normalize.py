from datetime import datetime

from ingest.models import LEAD_MAX_CHARS
from ingest.news.fetch import Feed, RawItem, parse_feed
from ingest.news.normalize import MSK, canonical_url, clean_text, make_lead, news_id, normalize, parse_date

RSS_CP1251 = """<?xml version="1.0" encoding="windows-1251"?>
<rss version="2.0"><channel><title>Лента</title>
<item>
  <title>Банк России сохранил ключевую ставку на уровне 14%</title>
  <link>https://www.example.ru/news/1?utm_source=rss</link>
  <description>&lt;p&gt;Совет директоров&amp;nbsp;принял решение.&lt;/p&gt;</description>
  <pubDate>Fri, 23 Oct 2026 13:30:00 +0300</pubDate>
</item>
</channel></rss>""".encode("cp1251")


def raw(**kw) -> RawItem:
    base = dict(
        feed_id="f",
        publisher="Издатель",
        priority=1,
        title="Заголовок",
        summary="",
        link="https://example.ru/a",
        published="Fri, 23 Oct 2026 10:00:00 +0000",
    )
    return RawItem(**(base | kw))


def test_clean_text_strips_html_entities_and_comments():
    html = "<!-- TypographyUse -->\n<p>Банк&nbsp;России &laquo;отозвал&raquo;\n  лицензию</p>"
    assert clean_text(html) == "Банк России «отозвал» лицензию"


def test_dateline_removed_from_lead():
    assert make_lead(" 22 октября. FINMARKET.RU - В систему страхования войдут банки.") == (
        "В систему страхования войдут банки."
    )
    assert make_lead("Москва. 23 октября. INTERFAX.RU - Минфин разместил ОФЗ.") == "Минфин разместил ОФЗ."


def test_lead_is_cut_to_limit_on_word_or_sentence():
    long_text = "Первое предложение про ставку. " + "слово " * 200
    lead = make_lead(long_text)
    assert len(lead) <= LEAD_MAX_CHARS
    assert lead.endswith("…") or lead.endswith(".")
    assert not lead.endswith(" …")


def test_lead_equal_to_title_is_dropped():
    assert make_lead("Заголовок новости", title="заголовок новости") == ""


def test_canonical_url_drops_tracking_and_fragment():
    assert (
        canonical_url("http://WWW.Example.ru/news/123/?utm_source=rss&id=5&from=main#comments")
        == "https://www.example.ru/news/123?id=5"
    )
    assert canonical_url("https://www.cbr.ru/press/event/?id=32927") == "https://www.cbr.ru/press/event?id=32927"


def test_parse_date_converts_to_moscow_time():
    dt = parse_date("Fri, 23 Oct 2026 10:00:00 +0000")
    assert dt == datetime(2026, 10, 23, 13, 0, tzinfo=MSK)
    assert dt.utcoffset().total_seconds() == 3 * 3600
    assert parse_date("2026-10-23T10:00:00Z") == dt
    assert parse_date("вчера") is None
    assert parse_date(None) is None


def test_normalize_builds_source_with_stable_id():
    src = normalize(raw(summary="<b>Лид</b> новости", link="https://example.ru/a?utm_medium=x"))
    assert src.kind == "news"
    assert src.url == "https://example.ru/a"
    assert src.id == news_id("https://example.ru/a")
    assert src.fragment == "Лид новости"
    assert src.published_at.utcoffset().total_seconds() == 3 * 3600


def test_normalize_uses_title_when_no_lead_and_skips_empty():
    assert normalize(raw(summary="")).fragment == "Заголовок"
    assert normalize(raw(title="  ")) is None
    assert normalize(raw(link="")) is None


def test_parse_feed_handles_cp1251_and_html_lead():
    items = parse_feed(Feed(id="t", publisher="Тест", url="https://example.ru/rss"), RSS_CP1251)
    assert len(items) == 1
    src = normalize(items[0])
    assert src.title == "Банк России сохранил ключевую ставку на уровне 14%"
    assert src.fragment == "Совет директоров принял решение."
    assert src.url == "https://www.example.ru/news/1"
    assert src.published_at == datetime(2026, 10, 23, 13, 30, tzinfo=MSK)
