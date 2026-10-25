"""Каталог источников: формат, связь с лентами, подключённость."""

import re

import pytest

from ingest.news.catalog import load_catalog
from ingest.news.fetch import Feed, load_feeds

# заметки разработчиков руководителю не показываем: техника — только в шагах подключения
JARGON = re.compile(
    r"\b(API|RSS|SOAP|JSON|REST|ключ\w* (API|доступ\w*)|сет\w* разработки|метод\w*|документаци\w*)\b", re.I
)


def test_texts_for_executive_have_no_developer_notes():
    for s in load_catalog():
        for text in (s.about, s.benefit, s.access, s.note or ""):
            assert not JARGON.search(text), (s.id, text)


def test_catalog_is_valid_and_matches_feeds():
    catalog = load_catalog()
    by_id = {s.id: s for s in catalog}
    enabled = {f.id for f in load_feeds() if f.enabled}
    # каждая включённая лента — в каталоге, и её источник отмечен подключённым
    in_catalog = {f for s in catalog for f in s.feeds}
    assert enabled <= in_catalog
    assert all(s.connected == any(f in enabled for f in s.feeds) for s in catalog)
    assert by_id["cbr"].connected and not by_id["rbc"].connected and not by_id["reuters"].connected
    assert {s.country for s in catalog} == {"ru", "intl"}
    assert by_id["cbr"].icon_url == "https://www.cbr.ru/favicon.ico" and by_id["reuters"].icon_url is None


def test_paid_sources_say_where_the_key_goes():
    for s in load_catalog():
        if s.kind == "paid_api" and s.id != "bloomberg":
            assert s.key_env and any(".env" in step for step in s.how_to_connect), s.id
        if s.kind == "paid_api":
            assert not s.feeds and not s.connected


def test_unknown_feed_and_duplicates_are_rejected(tmp_path):
    feeds = [Feed("a", "A", "https://a.ru/rss")]
    entry = 'id = "x"\nname = "X"\ncountry = "ru"\nkind = "free"\nreliability = "other"\nhow_to_connect = ["шаг"]\n'
    entry += 'about = "Что это"\nbenefit = "Что даст"\naccess = "Бесплатно"\n'
    path = tmp_path / "c.toml"
    path.write_text(f'[[source]]\n{entry}feeds = ["b"]\n', "utf-8")
    with pytest.raises(ValueError, match="нет лент"):
        load_catalog(str(path), feeds)
    path.write_text(f"[[source]]\n{entry}[[source]]\n{entry}", "utf-8")
    with pytest.raises(ValueError, match="дважды"):
        load_catalog(str(path), feeds)
    path.write_text(f"[[source]]\n{entry.replace('free', 'subscription')}", "utf-8")
    with pytest.raises(ValueError):
        load_catalog(str(path), feeds)
