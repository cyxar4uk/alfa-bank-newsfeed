"""Поиск по новостям и аналитике банка в настоящем PostgreSQL. Запускается, если задан TEST_DATABASE_URL."""

import os
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ingest.models import Mention, Source
from ingest.news.normalize import MSK, news_id
from ingest.news.pipeline import tag_source
from ingest.tagging.rules import tag

from api.search.models import PUBLIC_FRAGMENT_CHARS, AlfaFragment, short_fragment
from api.search.repo import SearchRepo, UnknownFilter
from api.search.routes import router

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL не задан")

NOW = datetime.now(MSK)


def news(n: str, title: str, lead: str = "", days: float = 0, publisher: str = "Интерфакс") -> Source:
    return tag_source(
        Source(
            id=f"src:news:{n}",
            kind="news",
            title=title,
            publisher=publisher,
            url=f"https://example.ru/{n}",
            published_at=NOW - timedelta(days=days),
            fragment=lead or title,
        )
    )


NEWS = [
    news(
        "rate",
        "Банк России сохранил ключевую ставку на уровне 14%",
        "Совет директоров Банка России принял решение сохранить ключевую ставку. Кредиты не подешевеют.",
        days=1,
        publisher="Банк России",
    ).model_copy(
        update={
            "image_url": "https://www.cbr.ru/p.jpg",
            "source_icon_url": "https://www.cbr.ru/favicon.ico",
            "text": "Полный текст пресс-релиза Банка России.",
        }
    ),
    news("mortgage", "Ставки по ипотеке выросли до максимума с весны", days=2),
    news("usd", "Курс доллара опустился ниже 81 рубля впервые с августа", days=1),
    news("oil", "Цена нефти Brent превысила $112 за баррель", days=0.5),
    news("vat", "Минфин предложил повысить ставку НДС для торговли", days=30),
    news("tree", "Ёлочные игрушки подорожали перед праздниками", days=3),
    news("cars", "Продажи автомобилей и автозапчастей выросли в сентябре", days=4),
]

MATERIAL = "src:alfa:keyrate-test"
PAGE1 = (
    "Ключевая ставка ЦБ РФ. Мы ожидаем сохранения ключевой ставки 14% до конца года.\nИнфляция замедлится."
)
PAGE2_OCR = "Прогноз | 2026 | 2027 каша из таблицы"
PAGE2_VLM = "Ставка, конец года, %: 14,0 в 2026 году и 11,0 в 2027 году."
# длинный фрагмент: искомое — в середине, наружу должно уйти окно не длиннее 600 знаков
LONG = (
    " ".join(["Обзор рынка облигаций федерального займа за неделю."] * 30)
    + (" Золото подорожало до рекорда на фоне ожиданий снижения ставки ФРС. ")
    + " ".join(["Спрос на длинные выпуски остаётся высоким."] * 30)
)


def alfa(id_: str, text: str, page: int, engine: str = "tesseract", material: str = MATERIAL, **kw) -> Source:
    return Source(
        id=id_,
        kind="alfa_analytics",
        title=kw.pop("title", "Ключевая ставка ЦБ РФ: без изменений"),
        publisher="Альфа-Банк",
        published_at=kw.pop("published_at", datetime(2026, 9, 11, tzinfo=MSK)),
        fragment=text,
        page=page,
        file=kw.pop("file", "ALFA-keyrate.pdf"),
        page_ref=f"{material}#p{page}",
        ocr_engine=engine,
        tags=tag("", text),
        **kw,
    )


@pytest.fixture(scope="module")
def repo():
    import psycopg
    from ingest.db.load import load_analytics, load_news, save_user_news
    from ingest.db.schema import ensure_schema
    from psycopg_pool import ConnectionPool

    with psycopg.connect(URL, autocommit=True) as conn:
        ensure_schema(conn)
        conn.execute("TRUNCATE news, alfa_materials, alfa_pages, alfa_fragments, search_loads")
        load_news(conn, NEWS)
        save_user_news(conn, news("user", "Присланная новость про ключевую ставку"), body="полный текст")
        pages = [
            alfa(f"{MATERIAL}#p1", PAGE1, 1),
            alfa(f"{MATERIAL}#p2", PAGE2_OCR, 2, vlm_text=PAGE2_VLM),
            alfa(f"{MATERIAL}#p3", LONG, 3),
            alfa("src:alfa:steel-old#p1", "Ставка на рост цен на сталь", 1, material="src:alfa:steel-old",
                 title="Российская сталь", published_at=datetime(2021, 4, 15, tzinfo=MSK), stale=True),
        ]  # fmt: skip
        fragments = [
            alfa(f"{MATERIAL}#p1-1", "Мы ожидаем сохранения ключевой ставки 14% до конца года.", 1),
            alfa(f"{MATERIAL}#p1-2", "Инфляция замедлится.", 1),
            alfa(f"{MATERIAL}#p2-1", PAGE2_VLM, 2, engine="qwen3-vl"),
            alfa(f"{MATERIAL}#p3-1", LONG, 3),
            alfa("src:alfa:steel-old#p1-1", "Ставка на рост цен на сталь", 1, material="src:alfa:steel-old",
                 title="Российская сталь", published_at=datetime(2021, 4, 15, tzinfo=MSK)),
        ]  # fmt: skip
        load_analytics(conn, pages, fragments)
    with ConnectionPool(URL, min_size=1, max_size=2) as pool:
        yield SearchRepo(pool)


def ids(items) -> list[str]:
    return [i.id.removeprefix("src:news:") for i in items]


@pytest.mark.parametrize(
    "query", ["ключевая ставка", "ключевую ставку", "ключевой ставкой", "ставки ключевые", "КЛЮЧЕВЫЕ СТАВКИ"]
)
def test_word_forms_find_the_same_news(repo, query):
    assert ids(repo.search_news(query, limit=3))[0] == "rate"


def test_yo_and_e_are_the_same(repo):
    assert ids(repo.search_news("елочные игрушки")) == ["tree"]
    assert ids(repo.search_news("ёлочный")) == ["tree"]


def test_all_query_words_rank_above_one(repo):
    found = repo.search_news("ставка ипотека", limit=10)
    assert ids(found)[0] == "mortgage"  # оба слова
    assert {"rate", "vat"} <= set(ids(found))  # одно слово — тоже в выдаче, ниже
    assert found[0].score > found[1].score


def test_filters(repo):
    assert ids(repo.search_news(factors=["fx"])) == ["usd"]
    assert ids(repo.search_news(factors=["курс валют"])) == ["usd"]  # название фактора
    assert "oil" in ids(repo.search_news(factors=["commodity_oil_gas"]))
    assert ids(repo.search_news("ставка", since=(NOW - timedelta(days=7)).date())) == ["rate", "mortgage"]
    assert "vat" not in ids(repo.search_news("ставка", since=NOW - timedelta(days=7)))
    cars = repo.search_news(sectors=["45"])
    assert (
        ids(cars)
        == ids(repo.search_news(sectors=["45.31.1"]))
        == ids(repo.search_news(sectors=["автомобили"]))
    )
    assert "cars" in ids(cars)
    with pytest.raises(UnknownFilter):
        repo.search_news(factors=["погода"])
    with pytest.raises(UnknownFilter):
        repo.search_news(sectors=["космос"])


def test_user_news_is_not_in_search_by_default(repo):
    assert "user" not in ids(repo.search_news("ключевая ставка", limit=20))
    assert "user" in ids(repo.search_news("ключевая ставка", limit=20, include_user=True))
    assert repo.get_source("src:news:user").title.startswith("Присланная")


def test_news_is_contract_source(repo):
    item = repo.search_news("ключевая ставка", limit=1)[0]
    assert item.kind == "news" and item.fragment.startswith("Совет директоров")
    assert item.url == "https://example.ru/rate" and item.published_at.utcoffset() == timedelta(hours=3)
    assert "rate" in [f.code for f in item.factors] and item.tags.topics


def test_news_image_icon_and_full_text(repo, client):
    item = repo.search_news("ключевая ставка", limit=1)[0]
    assert (item.image_url, item.source_icon_url) == (
        "https://www.cbr.ru/p.jpg",
        "https://www.cbr.ru/favicon.ico",
    )
    assert item.text is None  # полный текст — только у одной новости по id, не в списках
    assert repo.get_source("src:news:rate").text == "Полный текст пресс-релиза Банка России."
    assert client.get("/api/sources/src:news:rate").json()["image_url"] == "https://www.cbr.ru/p.jpg"
    other = repo.get_source("src:news:usd")
    assert (other.image_url, other.source_icon_url, other.text) == (None, None, None)


def test_alfa_search_returns_page_and_file(repo):
    found = repo.search_alfa_analytics("ожидаем сохранения ключевой ставки")
    top = found[0]
    assert isinstance(top, AlfaFragment)
    assert (top.page, top.file, top.material) == (1, "ALFA-keyrate.pdf", MATERIAL)
    assert top.page_ref == f"{MATERIAL}#p1" and top.published_at.date().isoformat() == "2026-09-11"
    assert "src:alfa:steel-old#p1-1" not in [f.id for f in found]  # устаревшее — не позиция банка
    stale = repo.search_alfa_analytics("ставка сталь", include_stale=True)
    assert "src:alfa:steel-old#p1-1" in [f.id for f in stale]


def test_alfa_topic(repo):
    assert f"{MATERIAL}#p1-2" in [f.id for f in repo.search_alfa_analytics("", topic="inflation")]
    by_material = repo.search_alfa_analytics("ставка", topic="keyrate-test")
    assert {f.material for f in by_material} == {MATERIAL}
    assert repo.search_alfa_analytics("", topic=None) == []
    # не фактор и не материал — слова добавляются к запросу
    assert repo.search_alfa_analytics("", topic="инфляция")[0].id == f"{MATERIAL}#p1-2"


def test_until_and_alfa_factors(repo):
    before = repo.search_news("ставка", until=NOW - timedelta(days=7))
    assert ids(before) == ["vat"]
    assert ids(
        repo.search_news("ставка", since=NOW - timedelta(days=7), until=NOW - timedelta(days=1.5))
    ) == ["mortgage"]
    found = repo.search_alfa_analytics("ставка", factors=["inflation"])
    assert found and all("inflation" in [f.code for f in x.factors] for x in found)


def test_alfa_page_text(repo):
    assert repo.alfa_page_text(f"{MATERIAL}#p1") == PAGE1
    assert repo.alfa_page_text(f"{MATERIAL}#p1-1") == PAGE1
    assert repo.alfa_page_text(f"{MATERIAL}#p2-1") == PAGE2_VLM  # фрагмент Qwen — текст Qwen
    assert repo.alfa_page_text(f"{MATERIAL}#p2") == PAGE2_OCR
    assert repo.alfa_page_text("src:alfa:нет#p1") is None


def test_verify_bank_quote(repo):
    assert repo.verify_bank_quote("сохранения  ключевой\nставки 14%", f"{MATERIAL}#p1-1")
    assert not repo.verify_bank_quote("ставка снизится до 10%", f"{MATERIAL}#p1-1")
    # фрагмент Qwen сверяется с текстом Qwen, а не Tesseract
    assert repo.verify_bank_quote("14,0 в 2026 году и 11,0 в 2027 году", f"{MATERIAL}#p2-1")
    assert repo.verify_bank_quote("14,0 в 2026 году и 11,0 в 2027 году", f"{MATERIAL}#p2")
    assert not repo.verify_bank_quote("цитата", "src:alfa:нет#p1")


def test_event_sources(repo):
    import psycopg
    from ingest.db.load import load_news

    head = news("ev", "Росстат зафиксировал рост цен на бензин в Москве", days=1)
    copy = news("ev2", "Росстат зафиксировал рост цен на бензин в Москве за неделю", days=1, publisher="РИА")
    with psycopg.connect(URL, autocommit=True) as conn:
        load_news(conn, [head])
        load_news(conn, [copy])
    sources = repo.get_event_sources("src:news:ev")
    assert [(s.id, s.publisher) for s in sources] == [
        ("src:news:ev", "Интерфакс"),
        (news_id("https://example.ru/ev2"), "РИА"),
    ]
    assert sources[1].fragment == copy.title
    assert repo.get_event_sources("src:news:нет") == []


@pytest.fixture(scope="module")
def client(repo):
    app = FastAPI()
    app.include_router(router)
    app.state.search = repo
    return TestClient(app)


def test_news_endpoint(client):
    body = client.get("/api/news", params={"factor": "fx"}).json()
    assert body["total"] == 1 and body["items"][0]["id"] == "src:news:usd"
    assert body["items"][0]["factors"][0]["code"] == "fx"
    page = client.get("/api/news", params={"limit": 2, "offset": 1}).json()
    assert len(page["items"]) == 2 and page["total"] >= len(NEWS)
    assert all(
        i["id"] != "src:news:user" for i in client.get("/api/news", params={"limit": 50}).json()["items"]
    )
    assert (
        client.get("/api/news", params={"q": "ключевую ставку"}).json()["items"][0]["id"] == "src:news:rate"
    )
    bad = client.get("/api/news", params={"factor": "погода"})
    assert bad.status_code == 422 and "неизвестный фактор" in bad.json()["detail"]


def test_sources_endpoint(client, repo):
    assert client.get("/api/sources/src:news:rate").json()["publisher"] == "Банк России"
    frag = client.get(f"/api/sources/{MATERIAL}%23p1-1").json()
    assert (frag["kind"], frag["page"], frag["file"]) == ("alfa_analytics", 1, "ALFA-keyrate.pdf")
    page = client.get(f"/api/sources/{MATERIAL}%23p2").json()
    assert page["page"] == 2 and page["fragment"] is None  # текст страницы наружу не отдаём
    assert client.get(f"/api/sources/{MATERIAL}").json()["title"].startswith("Ключевая ставка")
    assert client.get("/api/sources/src:news:нет").status_code == 404
    assert client.get("/api/sources/что-то").status_code == 404


def test_public_fragment_is_short():
    long = "слово " * 400
    short = short_fragment(long)
    assert len(short) <= PUBLIC_FRAGMENT_CHARS and short.endswith("…")
    assert short_fragment("коротко") == "коротко"


def test_long_alfa_fragment_is_a_short_window(repo, client):
    from api.contract import Insight

    hit = repo.search_alfa_analytics("золото рекорд")[0]
    assert hit.id == f"{MATERIAL}#p3-1"
    assert len(hit.fragment) <= PUBLIC_FRAGMENT_CHARS and "Золото подорожало" in hit.fragment
    assert hit.fragment.rstrip("…") in LONG  # окно дословное — цитату можно сверить со страницей
    assert hit.text == LONG  # весь фрагмент — агенту внутри сервиса
    insight = Insight(
        id="ins:x", event={"title": "т"}, relevance={"score": 0.5, "reason": "р"}, sources=[hit]
    )
    dumped = insight.model_dump_json()
    assert LONG not in dumped and "text" not in insight.model_dump()["sources"][0]
    body = client.get(f"/api/sources/{MATERIAL}%23p3-1").json()
    assert len(body["fragment"]) <= PUBLIC_FRAGMENT_CHARS and "text" not in body


def test_query_without_meaningful_words_finds_nothing(repo, client):
    for q in ["и в на", "???", "!", "'", "\\"]:
        assert repo.search_news(q) == [], q
        assert repo.search_alfa_analytics(q) == [], q
    assert client.get("/api/news", params={"q": "и в на"}).json()["total"] == 0


def test_null_byte_is_harmless(repo, client):
    assert repo.search_news("ставка \x00ключевая")[0].id == "src:news:rate"
    assert repo.get_source("src:alfa:\x00") is None
    assert repo.search_alfa_analytics("ставка\x00") is not None
    assert client.get("/api/sources/src:alfa:%00").status_code == 404


def test_news_without_date_is_not_fresh(repo):
    import psycopg
    from ingest.db.load import load_news

    undated = news("nodate", "Тарифы на электроэнергию для бизнеса вырастут")
    undated.published_at = None
    with psycopg.connect(URL, autocommit=True) as conn:
        load_news(conn, [undated, news("dated", "Минфин снизит тарифы для бизнеса", days=1)])
    assert ids(repo.search_news("тарифы для бизнеса"))[:2] == ["dated", "nodate"]


def test_total_past_the_last_page(repo):
    page = repo.list_news(limit=2, offset=10_000)
    assert page.items == [] and page.total >= len(NEWS)


def test_min_strength_without_factor(repo):
    import psycopg
    from ingest.db.load import load_news

    with psycopg.connect(URL, autocommit=True) as conn:
        load_news(conn, [news("plain", "Футбольный матч перенесли на воскресенье", days=1)])
    assert "plain" in ids(repo.search_news(limit=50))
    strong = repo.search_news(min_strength=0.3, limit=50)
    assert strong and "plain" not in ids(strong)
    assert all(any(f.strength >= 0.3 for f in n.factors) for n in strong)


def test_short_quote_is_not_a_check(repo):
    assert not repo.verify_bank_quote("14%", f"{MATERIAL}#p1-1")
    assert not repo.verify_bank_quote("ключевой ставки", f"{MATERIAL}#p1-1")


def test_user_news_is_not_an_event_source(repo):
    import psycopg
    from ingest.db.load import load_news, save_user_news

    head = news("ev3", "Минэнерго предложило ограничить экспорт дизельного топлива", days=1)
    mention_url = "https://example.ru/ev3-copy"
    head.also_reported_by = [Mention(publisher="РИА", title="Экспорт дизеля ограничат", url=mention_url)]
    fake = news("ev3-copy", "Выдуманный заголовок про дизель", publisher="подделка")
    fake.id, fake.url = news_id(mention_url), mention_url
    with psycopg.connect(URL, autocommit=True) as conn:
        load_news(conn, [head])
        save_user_news(conn, fake, body="подделка")
    sources = repo.get_event_sources("src:news:ev3")
    assert [(s.publisher, s.title) for s in sources[1:]] == [("РИА", "Экспорт дизеля ограничат")]


def test_schemas_created_concurrently_on_empty_db():
    import threading

    import psycopg
    from ingest.db.schema import ensure_schema as ensure_search

    from api.db import ensure_schema as ensure_api

    errors = []

    def run(fn):
        try:
            with psycopg.connect(URL, autocommit=True) as conn:
                fn(conn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    for _ in range(10):
        with psycopg.connect(URL, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS schema_meta")
        threads = [threading.Thread(target=run, args=(f,)) for f in (ensure_api, ensure_search)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == []


def test_null_byte_in_topic_and_event(repo):
    assert repo.search_alfa_analytics("ставка", topic="abc\x00") is not None
    assert repo.get_event_sources("src:news:\x00") == []
