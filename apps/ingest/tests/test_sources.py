"""Конфиг лент: надёжность, домены, условия; отсев записей с чужого домена."""

import pytest

from ingest.news.fetch import RELIABILITY, Feed, load_feeds, parse_feed
from ingest.news.normalize import normalize

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Правительство утвердило план</title><link>http://government.ru/news/1/</link><description>Лид.</description></item>
<item><title>Журнал о другом</title><link>https://rodina-history.ru/2026/1.html</link><description>Лид.</description></item>
</channel></rss>""".encode()


def test_every_feed_has_reliability_and_terms():
    feeds = load_feeds()
    assert {f.reliability for f in feeds} <= RELIABILITY
    assert all(f.terms for f in feeds), "условия использования указаны у каждой ленты"
    enabled = [f for f in feeds if f.enabled]
    assert all(f.hosts for f in enabled), "у включённой ленты заданы домены ссылок"
    assert {"government", "nalog", "rg", "izvestia", "kommersant-finance"} <= {f.id for f in enabled}
    assert {"prime", "rbc", "vedomosti-economics", "finmarket"} <= {f.id for f in feeds if not f.enabled}


def test_unknown_reliability_is_rejected(tmp_path):
    bad = tmp_path / "feeds.toml"
    bad.write_text('[[feed]]\nid = "x"\npublisher = "X"\nurl = "https://x.ru/rss"\nreliability = "блог"\n', "utf-8")
    with pytest.raises(ValueError, match="reliability"):
        load_feeds(str(bad))


def test_items_from_other_hosts_are_skipped_and_reliability_is_carried():
    feed = Feed(id="government", publisher="Правительство России", url="http://government.ru/all/rss/",
                reliability="official", hosts=("government.ru",))  # fmt: skip
    items = parse_feed(feed, RSS)
    assert [i.link for i in items] == ["http://government.ru/news/1/"]
    src = normalize(items[0])
    assert (src.publisher, src.reliability) == ("Правительство России", "official")
