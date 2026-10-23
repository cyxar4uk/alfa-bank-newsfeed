from datetime import datetime, timedelta

from ingest.models import Source
from ingest.news.dedup import deduplicate
from ingest.news.fetch import RawItem
from ingest.news.normalize import MSK
from ingest.news.pipeline import build_news

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=MSK)


def news(id_, title, publisher="СМИ", url=None, at=T0, lead=None) -> Source:
    return Source(
        id=id_,
        kind="news",
        title=title,
        publisher=publisher,
        url=url or f"https://example.ru/{id_}",
        published_at=at,
        fragment=lead or title,
    )


def test_same_story_from_different_publishers_is_merged_and_regulator_leads():
    items = [
        news("a", "ЦБ сохранил ключевую ставку на уровне 14%", "Интерфакс", lead="Лид Интерфакса"),
        news(
            "b", "Банк России сохранил ключевую ставку на уровне 14% годовых", "Банк России", at=T0 - timedelta(hours=1)
        ),
        news("c", "Ключевая ставка сохранена на уровне 14%", "Коммерсантъ", at=T0 + timedelta(hours=2)),
    ]
    out = deduplicate(items, priority={"a": 1, "b": 0, "c": 2})
    assert len(out) == 1
    assert out[0].publisher == "Банк России"
    assert {m.publisher for m in out[0].also_reported_by} == {"Интерфакс", "Коммерсантъ"}


def test_same_url_in_two_feeds_kept_once():
    a = news("x1", "Цена нефти Brent превысила $112", url="https://kommersant.ru/doc/1")
    b = news("x2", "Цена нефти Brent превысила $112", url="https://kommersant.ru/doc/1")
    out = deduplicate([a, b])
    assert len(out) == 1
    assert out[0].also_reported_by == []


def test_template_titles_about_different_places_are_not_merged():
    items = [
        news("1", "В аэропорту Сочи ввели временные ограничения"),
        news("2", "В аэропорту Казани ввели временные ограничения"),
        news("3", "В аэропорту Саранска ввели временные ограничения"),
        news("4", "В аэропортах Бугульмы и Нижнекамска ввели временные ограничения"),
        news("5", "В аэропорту Нижнего Новгорода ввели временные ограничения"),
    ]
    assert len(deduplicate(items)) == 5


def test_same_place_in_different_case_still_merges():
    items = [
        news("1", "16 человек погибли при землетрясении в Китае", "Интерфакс"),
        news("2", "Землетрясение в Китае: погибли 16 человек", "РИА Новости"),
    ]
    assert len(deduplicate(items)) == 1


def test_different_numbers_are_different_events():
    items = [news("1", "ЦБ повысил ключевую ставку до 16%"), news("2", "ЦБ повысил ключевую ставку до 14%")]
    assert len(deduplicate(items)) == 2


def test_same_title_far_apart_in_time_is_not_merged():
    items = [
        news("1", "Минфин разместил ОФЗ на аукционе"),
        news("2", "Минфин разместил ОФЗ на аукционе", at=T0 + timedelta(days=7)),
    ]
    assert len(deduplicate(items)) == 2


def test_unrelated_news_stay_separate_and_sorted_newest_first():
    items = [
        news("1", "Росстат: инфляция в сентябре замедлилась", at=T0 - timedelta(hours=5)),
        news("2", "Северсталь отчиталась о росте выручки", at=T0),
    ]
    out = deduplicate(items)
    assert [s.id for s in out] == ["2", "1"]


def test_build_news_normalizes_dedups_and_tags():
    raw = [
        RawItem(
            "cbr",
            "Банк России",
            0,
            "Банк России сохранил ключевую ставку 14%",
            "",
            "https://cbr.ru/press/1",
            "Fri, 23 Oct 2026 13:30:00 +0300",
        ),
        RawItem(
            "ifx",
            "Интерфакс",
            1,
            "ЦБ РФ сохранил ключевую ставку 14%",
            "Совет директоров Банка России...",
            "https://interfax.ru/1",
            "Fri, 23 Oct 2026 13:31:00 +0300",
        ),
    ]
    out = build_news(raw)
    assert len(out) == 1
    assert out[0].publisher == "Банк России"
    assert "rate" in [f.code for f in out[0].tags.factors]
    assert out[0].tags.tagged_by == ["rules"]


def test_chain_of_similar_titles_does_not_glue_different_events():
    items = [
        news("1", "Цены на бензин Аи-95 обновили рекорд на бирже", at=T0),
        news("2", "Цены на бензин Аи-95 на бирже снизились", at=T0 + timedelta(hours=1)),
        news("3", "Цены на дизель на бирже снизились после рекорда", at=T0 + timedelta(hours=2)),
    ]
    out = deduplicate(items)
    # «1» и «3» не похожи напрямую — даже если каждый похож на «2», это не один сюжет
    assert not any({m.title for m in o.also_reported_by} >= {items[0].title, items[2].title} for o in out)
    assert len(out) >= 2
