"""Загрузка в PostgreSQL. Запускается, если задан TEST_DATABASE_URL (таблицы материалов очищаются)."""

import os
from datetime import datetime, timedelta

import pytest

from ingest import cli
from ingest.db.load import load_all, load_analytics, load_news, read_jsonl, save_user_news
from ingest.db.schema import META_KEY, ensure_schema
from ingest.models import Mention, Source, Tags
from ingest.news.normalize import MSK, news_id
from ingest.news.pipeline import tag_source

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL не задан")

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=MSK)


def news(n: str, title: str, lead: str = "", publisher: str = "Интерфакс", hours: float = 0, **kw) -> Source:
    src = Source(
        id=f"src:news:{n}",
        kind="news",
        title=title,
        publisher=publisher,
        url=f"https://example.ru/{n}",
        published_at=NOW - timedelta(hours=hours),
        fragment=lead or title,
        **kw,
    )
    return tag_source(src)


def page(material: str, n: int, text: str, vlm: str | None = None, stale: bool = False) -> Source:
    return Source(
        id=f"src:alfa:{material}#p{n}",
        kind="alfa_analytics",
        title=f"Материал {material}",
        publisher="Альфа-Банк",
        published_at=NOW - timedelta(days=40),
        fragment=text,
        page=n,
        file=f"{material}.pdf",
        vlm_text=vlm,
        stale=stale or None,
    )


def fragment(material: str, n: int, k: int, text: str, engine: str = "tesseract") -> Source:
    return Source(
        id=f"src:alfa:{material}#p{n}-{k}",
        kind="alfa_analytics",
        title=f"Материал {material}",
        publisher="Альфа-Банк",
        published_at=NOW - timedelta(days=40),
        fragment=text,
        page=n,
        file=f"{material}.pdf",
        page_ref=f"src:alfa:{material}#p{n}",
        ocr_engine=engine,
        tags=Tags(),
    )


@pytest.fixture
def conn():
    import psycopg

    with psycopg.connect(URL, autocommit=True) as c:
        ensure_schema(c)
        c.execute("TRUNCATE news, alfa_materials, alfa_pages, alfa_fragments, search_loads")
        yield c


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_news_load_is_idempotent(conn):
    items = [
        news("a", "Банк России сохранил ключевую ставку 14%", "Совет директоров принял решение.", "Банк России"),
        news("b", "Цена нефти Brent превысила $112 за баррель", hours=3),
    ]
    first = load_news(conn, items)
    assert (first.read, first.inserted) == (2, 2)
    again = load_news(conn, items)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 2)
    assert count(conn, "news") == 2

    row = conn.execute(
        "SELECT factors, okved, tags->'factors'->0->>'code' FROM news WHERE id = 'src:news:a'"
    ).fetchone()
    assert "rate" in row[0] and row[2] is not None
    oil = conn.execute("SELECT id FROM news WHERE 'commodity_oil_gas' = ANY(factors)").fetchall()
    assert oil == [("src:news:b",)]


def test_changed_news_is_updated_not_duplicated(conn):
    load_news(conn, [news("a", "Банк России сохранил ключевую ставку 14%")])
    first_seen = conn.execute("SELECT first_seen_at FROM news").fetchone()[0]
    stats = load_news(conn, [news("a", "Банк России сохранил ключевую ставку 14%", "Лид появился позже.")])
    assert (stats.updated, stats.inserted) == (1, 0)
    row = conn.execute("SELECT fragment, first_seen_at FROM news").fetchone()
    assert row == ("Лид появился позже.", first_seen)


def test_same_story_from_later_run_joins_existing_event(conn):
    load_news(conn, [news("a", "Банк России сохранил ключевую ставку на уровне 14%", publisher="Банк России")])
    # следующий прогон: первой записи в ленте уже нет, тот же сюжет пришёл от другого издателя
    later = news("b", "ЦБ сохранил ключевую ставку на уровне 14%", publisher="РИА Новости", hours=-2)
    stats = load_news(conn, [later])
    assert (stats.inserted, stats.merged) == (0, 1)
    assert count(conn, "news") == 1
    mentions = conn.execute("SELECT also_reported_by FROM news WHERE id = 'src:news:a'").fetchone()[0]
    assert [m["url"] for m in mentions] == ["https://example.ru/b"]
    # повтор того же прогона ничего не добавляет
    load_news(conn, [later])
    assert len(conn.execute("SELECT also_reported_by FROM news").fetchone()[0]) == 1


def test_different_events_are_not_merged(conn):
    load_news(conn, [news("a", "Банк России повысил ключевую ставку до 16%")])
    stats = load_news(conn, [news("b", "Банк России повысил ключевую ставку до 14%", hours=-1)])
    assert stats.inserted == 1 and count(conn, "news") == 2
    # тот же заголовок, но через неделю — другое событие
    stats = load_news(conn, [news("c", "Банк России повысил ключевую ставку до 16%", hours=-24 * 7)])
    assert stats.inserted == 1


def test_mentions_from_parser_are_kept_and_merged(conn):
    head = news("a", "Курс доллара опустился ниже 81 рубля впервые с августа")
    head.also_reported_by = [Mention(publisher="РИА", title="Доллар ниже 81 рубля", url="https://example.ru/m1")]
    load_news(conn, [head])
    head2 = head.model_copy(
        update={"also_reported_by": [Mention(publisher="Forbes", title="Доллар ниже 81", url="https://example.ru/m2")]}
    )
    load_news(conn, [head2])
    urls = [m["url"] for m in conn.execute("SELECT also_reported_by FROM news").fetchone()[0]]
    assert urls == ["https://example.ru/m1", "https://example.ru/m2"]
    # упомянутая запись, пришедшая отдельно, не становится вторым событием
    stats = load_news(conn, [news("m1", "Доллар ниже 81 рубля", publisher="РИА")])
    assert stats.merged == 1 and count(conn, "news") == 1


def test_analytics_replaced_as_a_set(conn):
    pages = [page("keyrate", 1, "Мы ожидаем сохранения ключевой ставки 14% до конца года.")]
    frags = [
        fragment("keyrate", 1, 1, "Мы ожидаем сохранения ключевой ставки 14%"),
        fragment("keyrate", 1, 2, "до конца года."),
        fragment("keyrate", 9, 1, "фрагмент без своей страницы"),
    ]
    stats = load_analytics(conn, pages, frags, signature="v1")
    assert (stats.materials, stats.pages, stats.fragments) == (1, 1, 2)
    assert load_analytics(conn, pages, frags, signature="v1").skipped
    load_analytics(conn, pages, frags[:1], signature="v2")
    assert count(conn, "alfa_fragments") == 1
    row = conn.execute("SELECT file, pages, stale FROM alfa_materials").fetchone()
    assert row == ("keyrate.pdf", 1, False)


def test_schema_migration_keeps_api_tables(conn):
    # таблица и ключ версии API (api.db): миграция материалов не должна их трогать
    conn.execute("CREATE TABLE IF NOT EXISTS companies (id text)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', 'api-probe') ON CONFLICT DO NOTHING")
    api_version = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()[0]
    load_news(conn, [news("a", "Банк России сохранил ключевую ставку 14%")])
    conn.execute("UPDATE schema_meta SET value = '0' WHERE key = %s", (META_KEY,))
    # API при старте другую версию не пересоздаёт: история новостей остаётся
    assert ensure_schema(conn) is False and count(conn, "news") == 1
    assert ensure_schema(conn, migrate=True) is True
    assert count(conn, "news") == 0
    assert conn.execute("SELECT to_regclass('companies')").fetchone()[0] is not None
    assert conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()[0] == api_version
    assert ensure_schema(conn, migrate=True) is False
    if api_version == "api-probe":
        conn.execute("DELETE FROM schema_meta WHERE key = 'version'")


def write_jsonl(path, items, broken: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(i.model_dump_json(exclude_none=True) + "\n" for i in items)
    path.write_text(lines + ("{битая строка\n" if broken else ""), "utf-8")


def test_load_all_from_data_dir(conn, tmp_path):
    write_jsonl(tmp_path / "demo" / "news_snapshot.jsonl", [news("a", "Банк России сохранил ключевую ставку 14%")])
    write_jsonl(tmp_path / "raw" / "derived" / "news.jsonl", [news("b", "Цена нефти Brent превысила $112")])
    write_jsonl(tmp_path / "raw" / "derived" / "alfa_pages.jsonl", [page("gold", 2, "Золото подорожало")])
    write_jsonl(tmp_path / "raw" / "derived" / "alfa_fragments.jsonl", [fragment("gold", 2, 1, "Золото подорожало")])
    assert len(read_jsonl(tmp_path / "demo" / "news_snapshot.jsonl")) == 1  # битая строка пропущена

    result = load_all(conn, tmp_path)
    assert result["snapshot"]["inserted"] == 1 and result["news"]["inserted"] == 1
    assert result["analytics"]["fragments"] == 1
    again = load_all(conn, tmp_path)
    assert again["snapshot"]["unchanged"] == 1 and again["analytics"]["skipped"]
    assert count(conn, "news") == 2


def test_serve_without_network_keeps_what_is_loaded(conn, tmp_path, monkeypatch, capsys):
    from ingest.news.fetch import FeedReport

    down = FeedReport("cbr", "Банк России", "https://cbr.ru/rss", ok=False, error="нет сети")
    fresh = news("a", "Банк России сохранил ключевую ставку 14%", "Свежий лид из ленты.")
    answers = iter([([], [down]), ([fresh], []), ([], [down])])
    monkeypatch.setattr(cli, "collect_news", lambda feeds: next(answers))
    snapshot = [news("a", "Банк России сохранил ключевую ставку 14%", "Старый лид из снимка.")]
    write_jsonl(tmp_path / "demo" / "news_snapshot.jsonl", snapshot, broken=False)

    cli.run_serve(tmp_path, URL, every=0, iterations=3)
    out = capsys.readouterr().out
    assert "ленты не ответили — в базе остаётся загруженное" in out
    assert conn.execute("SELECT fragment FROM news").fetchall() == [("Свежий лид из ленты.",)]
    assert not (tmp_path / "raw").exists()  # сервис файлы не пишет

    # перезапуск: снимок не откатывает свежую версию
    load_all(conn, tmp_path)
    assert conn.execute("SELECT fragment FROM news").fetchall() == [("Свежий лид из ленты.",)]


def test_user_news_from_feed_joins_existing_event(conn):
    load_news(conn, [news("a", "Банк России сохранил ключевую ставку на уровне 14%", publisher="Банк России")])
    user = news("b", "ЦБ сохранил ключевую ставку на уровне 14%", publisher="РИА Новости", hours=-1)
    user.id = news_id(user.url)  # как у разбора по ссылке и у парсера
    save_user_news(conn, user, body="текст")
    stats = load_news(conn, [user])
    assert stats.merged == 1
    rows = dict(conn.execute("SELECT id, origin FROM news").fetchall())
    assert rows == {"src:news:a": "feed", user.id: "user"}  # ссылки инсайтов на присланную не ломаются
    mentions = conn.execute("SELECT also_reported_by FROM news WHERE id = 'src:news:a'").fetchone()[0]
    assert [m["url"] for m in mentions] == ["https://example.ru/b"]


def test_user_row_does_not_swallow_feed_mention(conn):
    copy_url = "https://example.ru/copy"
    save_user_news(conn, news("x", "Копия сюжета, присланная пользователем").model_copy(
        update={"id": news_id(copy_url), "url": copy_url}), body="текст")  # fmt: skip
    head = news("h", "Росстат зафиксировал рост цен на бензин в Москве")
    head.also_reported_by = [Mention(publisher="РИА", title="Бензин подорожал", url=copy_url)]
    load_news(conn, [head])
    mentions = conn.execute("SELECT also_reported_by FROM news WHERE id = 'src:news:h'").fetchone()[0]
    assert [m["url"] for m in mentions] == [copy_url]


def test_user_news_of_a_new_story_becomes_feed_event(conn):
    user = news("c", "Минпромторг предложил новые правила маркировки шин")
    save_user_news(conn, user, body="текст")
    assert load_news(conn, [user]).updated == 1
    assert conn.execute("SELECT origin, body FROM news").fetchone() == ("feed", "текст")


def test_mention_with_its_own_row_is_not_duplicated(conn):
    a = news("a", "Курс доллара опустился ниже 81 рубля впервые с августа")
    b = news("b", "Минфин увеличил продажи валюты в рамках бюджетного правила")
    b.id = news_id(b.url)  # как у парсера: id новости — от её ссылки
    load_news(conn, [a, b])
    c = news("c", "Курс доллара опустился ниже 81 рубля", publisher="РИА", hours=-1)
    c.also_reported_by = [Mention(publisher="Forbes", title=b.title, url=b.url)]
    load_news(conn, [c])
    mentions = conn.execute("SELECT also_reported_by FROM news WHERE id = 'src:news:a'").fetchone()[0]
    assert [m["url"] for m in mentions] == ["https://example.ru/c"]  # b — своё событие, не упоминание
    assert count(conn, "news") == 2


def test_snapshot_only_adds(conn, tmp_path):
    load_news(conn, [news("a", "Банк России сохранил ключевую ставку 14%", "Свежий лид.")])
    write_jsonl(tmp_path / "demo" / "news_snapshot.jsonl", [news("a", "Банк России сохранил ключевую ставку 14%")])
    assert load_all(conn, tmp_path)["snapshot"]["unchanged"] == 1
    assert conn.execute("SELECT fragment FROM news").fetchone()[0] == "Свежий лид."


def test_serve_retries_initial_load(conn, tmp_path, monkeypatch, capsys):
    import psycopg

    calls = []

    def flaky(data, url):
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.OperationalError("БД ещё не поднялась")
        return {}

    monkeypatch.setattr(cli, "run_load", flaky)
    monkeypatch.setattr(cli, "collect_news", lambda feeds: ([], []))
    cli.run_serve(tmp_path, URL, every=0, iterations=3)
    assert len(calls) == 2  # упала — повторили на следующем круге, удалась — больше не грузим
    assert "БД ещё не поднялась" in capsys.readouterr().out


def test_reliability_is_stored(conn):
    item = news("r", "Правительство утвердило план по снижению ключевой ставки").model_copy(
        update={"reliability": "official"}
    )
    load_news(conn, [item])
    assert conn.execute("SELECT reliability FROM news WHERE id = 'src:news:r'").fetchone()[0] == "official"
