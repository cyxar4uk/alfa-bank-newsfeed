import pytest
from factories import make_company
from fastapi.testclient import TestClient

from api.contract import ImportedFile
from api.main import app, get_repo, news_provider
from api.records import Flow, GroupStats


class FakeRepo:
    def __init__(self):
        self.companies = {
            "U_1": make_company(),
            "U_2": make_company(id="U_2", okved_code="49.41", okved_name="Грузоперевозки", revenue=5e8),
            "U_4": make_company(
                id="U_4",
                okved_code="35.11",
                okved_name="Производство электроэнергии",
                revenue=16e9,
                group_id="group_4_sb",
            ),
            # потенциальный клиент: ему лента не положена
            "U_5": make_company(id="U_5", revenue=1e8, client_type="PROSPECT", group_id="group_5_sb"),
        }

    def get_company(self, company_id):
        return self.companies.get(company_id)

    def list_companies(self, large, limit, offset, clients_only=False, per_group=False):
        stats = self.group_stats([c.group_id for c in self.companies.values() if c.group_id])

        def basis(c):
            return (stats[c.group_id].revenue if c.group_id in stats else None) or c.revenue or 0

        items = sorted(self.companies.values(), key=lambda c: (-basis(c), -(c.revenue or 0)))
        if large:
            items = [c for c in items if basis(c) > 15e9]
        if clients_only:
            items = [c for c in items if c.client_type == "CLIENT"]
        if per_group:
            seen, unique = set(), []
            for c in items:
                if (c.group_id or c.id) not in seen:
                    seen.add(c.group_id or c.id)
                    unique.append(c)
            items = unique
        return items[offset : offset + limit]

    def group_stats(self, group_ids):
        result = {}
        for g in set(group_ids):
            members = [c for c in self.companies.values() if c.group_id == g]
            result[g] = GroupStats(
                revenue=sum(c.revenue or 0 for c in members) or None,
                size=len(members),
                clients=sum(c.client_type == "CLIENT" for c in members),
            )
        return result

    def group(self, group_id, exclude, limit):
        return 2, ["U_2"]

    def flows(self, company_id):
        return [Flow("U_2", "out", 1e9, 5, self.companies["U_2"])] if company_id == "U_1" else []

    def group_records(self, group_id, exclude):
        return [c for c in self.companies.values() if c.group_id == group_id and c.id != exclude]

    def industry(self, company):
        return None

    def imported_files(self):
        return [
            ImportedFile(
                file="x.csv", rows_read=1, rows_loaded=1, rows_skipped=0, loaded_at="2026-10-23T00:00:00Z"
            )
        ]


@pytest.fixture
def client():
    app.dependency_overrides[get_repo] = FakeRepo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_without_case_data(client):
    response = client.get("/api/health")
    assert response.status_code == 200  # API живо
    body = response.json()
    assert (body["db"], body["status"]) == ("ok", "degraded")
    assert len(body["warnings"]) == 3  # ни одного файла кейса не загружено
    assert body["warnings"][0].startswith("файл df_Uid_data_hack.csv не загружен: положите CSV кейса")


def test_health_with_case_data(client):
    files = [
        ImportedFile(
            file=name,
            rows_read=10,
            rows_loaded=10 if i else 0,
            rows_skipped=0,
            loaded_at="2026-10-23T00:00:00Z",
        )
        for i, name in enumerate(
            ["df_Uid_data_hack.csv", "df_Uid_payment_hack.csv", "df_Fid_Uid_link_hack.csv"]
        )
    ]
    app.dependency_overrides[get_repo] = lambda: type(
        "R", (FakeRepo,), {"imported_files": lambda self: files}
    )()
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["warnings"] == ["файл df_Uid_data_hack.csv загружен, но в нём нет ни одной годной строки"]


def test_company_profile(client):
    response = client.get("/api/companies/U_1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "U_1"
    assert body["group"] == {"id": "group_1_sb", "size": 2, "revenue": 20.5e9, "members": ["U_2"]}
    features = {f["id"]: f for f in body["features"]}
    assert features["feat:group_revenue"]["value"] == 20.5e9
    assert features["feat:scale"]["display"].startswith("крупный бизнес по выручке группы (20,5 млрд ₽)")
    assert body["counterparties"][0]["sector"] == "транспорт и логистика"
    assert {f["id"] for f in body["features"]} >= {
        "feat:sector",
        "feat:REVENUE_COMPANY",
        "feat:top_counterparties",
    }


def test_exposure(client):
    response = client.get("/api/companies/U_1/exposure")
    assert response.status_code == 200
    body = response.json()
    assert body["company_id"] == "U_1"
    assert body["catalog_version"]
    factors = {f["code"]: f for f in body["factors"]}
    assert factors["rate"]["level"] == "high"
    assert factors["rate"]["id"] == "exp:rate"
    assert factors["rate"]["evidence"][0]["ref"] == "feat:CL_PRODUCT_LOA_MARK"
    assert client.get("/api/companies/U_404/exposure").status_code == 404


def test_chain(client):
    response = client.get("/api/companies/U_1/chain", params={"okved": ["49", "35"]})
    assert response.status_code == 200
    body = response.json()
    assert body["event_okved"] == ["49", "35"]
    # перевозчик U_2 — из той же группы: платежи ему внутригрупповые, канал — группа, а не поставщики
    # весь оборот U_1 — с перевозчиком U_2 из своей группы; энергетик U_4 — в другой группе, канала по 35 нет
    assert [(c["kind"], c["okved"]) for c in body["channels"]] == [("group", "49")]
    assert body["channels"][0]["nodes"][0]["id"] == "U_2"
    assert client.get("/api/companies/U_1/chain", params={"okved": "49,35"}).json()["event_okved"] == [
        "49",
        "35",
    ]
    assert client.get("/api/companies/U_1/chain").status_code == 422  # без okved
    assert client.get("/api/companies/U_404/chain", params={"okved": "49"}).status_code == 404


def test_company_not_found(client):
    assert client.get("/api/companies/U_404").status_code == 404


def test_large_companies(client):
    body = client.get("/api/companies", params={"large": "true"}).json()
    # крупный бизнес — по выручке группы: U_2 с выручкой 0,5 млрд — в группе на 20,5 млрд
    assert [c["id"] for c in body] == ["U_1", "U_2", "U_4"]
    assert body[0]["sector"] == "оптовая торговля"
    u2 = body[1]
    assert (u2["revenue"], u2["group_revenue"], u2["group_size"], u2["large"]) == (5e8, 20.5e9, 2, True)
    leaders = client.get("/api/companies", params={"large": "true", "per_group": "true"}).json()
    assert [c["id"] for c in leaders] == ["U_1", "U_4"]


def test_personas(client):
    body = client.get("/api/personas").json()
    assert {p["company_id"] for p in body} == {"U_1", "U_4"}
    assert all(p["role_label"] and p["company_name"] for p in body)


def test_openapi(client):
    assert client.get("/api/openapi.json").status_code == 200


class FakeNews:
    name = "тест"

    def events(self, since, limit):
        import datetime as dt

        from api.ranking import MSK, NewsEvent

        now = dt.datetime.now(MSK)
        return [
            NewsEvent(
                id="src:news:rate", title="Ставка", published_at=now, factors=[("rate", 1.0, "ставка")]
            ),
            NewsEvent(
                id="src:news:gold", title="Золото", published_at=now, factors=[("commodity_gold", 1.0, "")]
            ),
        ]

    def has_bank_view(self, factors):
        return "rate" in factors


def test_feed(client):
    app.dependency_overrides[news_provider] = FakeNews
    body = client.get("/api/feed", params={"persona": "p-u1-cfo"}).json()
    assert (body["company_id"], body["role"], body["candidates"], body["news_source"]) == (
        "U_1",
        "cfo",
        2,
        "тест",
    )
    assert [i["event_id"] for i in body["items"]] == ["src:news:rate"]  # золото компанию не задевает
    item = body["items"][0]
    assert item["has_bank_view"] is True
    assert item["relevance"]["breakdown"][0]["code"] == "rate"
    assert item["short"] is None  # «собственный кредит в банке» — числа нет, экран возьмёт channel_text
    assert client.get("/api/feed", params={"persona": "p-u404-cfo"}).status_code == 404
    assert client.get("/api/feed", params={"persona": "кто-то"}).status_code == 404
    # брифинг — то же, что лента (так его вызывает фронт)
    briefing = client.get("/api/briefing", params={"persona": "p-u1-cfo"}).json()
    assert briefing["items"][0]["event_id"] == "src:news:rate"
    # U_5 — потенциальный клиент: лента только для действующих
    assert client.get("/api/feed", params={"persona": "p-u5-cfo"}).status_code == 404


def test_empty_news_base_falls_back_to_snapshot(tmp_path):
    from api.news import FallbackNews, SnapshotNews

    class EmptySearch:
        name = "база новостей"

        def events(self, since, limit):
            return []

        def has_bank_view(self, factors):
            return True

    snapshot = tmp_path / "news.jsonl"
    good = (
        '{"id": "src:news:s", "title": "Ставка", "published_at": "2026-10-23T10:00:00+03:00",'
        ' "tags": {"factors": [{"code": "rate", "strength": 1}]}}'
    )
    snapshot.write_text("\n".join([good, "{битая строка", ""]), "utf-8")
    news = FallbackNews(EmptySearch(), SnapshotNews(snapshot))
    assert [e.id for e in news.events(None, 10)] == ["src:news:s"]
    assert news.name.startswith("снимок")
    assert news.has_bank_view(["rate"]) is False  # в снимке аналитики нет
    # событие по id: в базе нет — из снимка
    EmptySearch.event = lambda self, event_id: None
    assert news.event("src:news:s").title == "Ставка"
    assert news.event("src:news:нет") is None


def test_group_impact_endpoint(client):
    body = client.get("/api/companies/U_1/group-impact", params={"okved": "49"}).json()
    assert body["affected_count"] == 1
    assert body["affected"][0]["id"] == "U_2"  # перевозчик из той же группы
    assert body["intra_payments"] == 1e9
    # U_4 — одна в своей группе: блока нет
    assert client.get("/api/companies/U_4/group-impact", params={"okved": "35"}).json() is None
    assert client.get("/api/companies/U_404/group-impact", params={"okved": "49"}).status_code == 404
    # без события ответ «группу не касается» был бы ложным
    assert client.get("/api/companies/U_1/group-impact").status_code == 422


class RateNews(FakeNews):
    """Событие только про ставку: отраслей в разметке нет."""

    def event(self, event_id):
        return next((e for e in self.events(None, 10) if e.id == event_id), None)


def test_group_impact_by_event_counts_factor_events(client):
    # «ЦБ сохранил ставку» без ОКВЭД: участник группы с кредитом затронут через стоимость заёмных денег
    from api.main import optional_news

    app.dependency_overrides[optional_news] = RateNews
    body = client.get("/api/companies/U_1/group-impact", params={"event_id": "src:news:rate"}).json()
    assert body["affected_count"] == 1
    member = body["affected"][0]
    assert (member["id"], member["direct"]) == ("U_2", False)
    assert [f["code"] for f in member["factors"]] == ["rate"]
    assert "событие касается 1 компании группы" in body["text"]
    # золото участника группы не задевает
    gold = client.get("/api/companies/U_1/group-impact", params={"event_id": "src:news:gold"}).json()
    assert gold["affected_count"] == 0
    missing = client.get("/api/companies/U_1/group-impact", params={"event_id": "src:news:нет"})
    assert missing.status_code == 404


def test_feed_group_impact_only_for_owner_and_ceo(client):
    app.dependency_overrides[news_provider] = GroupNews
    owner = client.get("/api/feed", params={"persona": "p-u1-owner"}).json()["items"][0]
    assert owner["group_impact"]["affected"][0]["id"] == "U_2"
    cfo = client.get("/api/feed", params={"persona": "p-u1-cfo"}).json()["items"][0]
    assert cfo["group_impact"] is None


class GroupNews(FakeNews):
    def events(self, since, limit):
        import datetime as dt

        from api.ranking import MSK, NewsEvent

        return [
            NewsEvent(
                id="src:news:trucks",
                title="Грузоперевозки",
                published_at=dt.datetime.now(MSK),
                factors=[("rate", 1.0, "ставка")],
                sectors=[("49", 1.0)],
            )
        ]


def test_ved_countries_of_company_group_and_major_counterparties():
    from api.service import ved_countries

    company = make_company(fts_countries="КИТАЙ")
    member = make_company(id="U_2", fts_countries="ЛИТВА")
    major = make_company(id="U_3", fts_countries="ТУРЦИЯ")
    minor = make_company(id="U_4", fts_countries="ИНДИЯ")
    flows = [Flow("U_3", "in", 99.0, 1, major), Flow("U_4", "out", 0.5, 1, minor)]
    # контрагент меньше 1 % оборота — не канал
    assert ved_countries(company, [member], flows) == {"Китай", "Литва", "Турция"}
    # ВЭД без стран — страны неизвестны
    assert ved_countries(make_company(fts_countries=None), [], []) is None


def test_search_news_event_by_id():
    from api.news import SearchNews

    class Search:
        def get_source(self, source_id):
            return {"id": source_id, "title": "Ставка", "factors": [{"code": "rate", "strength": 1}]}

    news = SearchNews(Search())
    assert news.event("src:news:a").factors == [("rate", 1.0, "rate")]
    assert news.event("src:alfa:x#p1") is None  # аналитика банка — не событие


def test_group_impact_by_event_uses_its_sectors_and_needs_news(client):
    from api.main import optional_news
    from api.ranking import NewsEvent

    class TruckNews(RateNews):
        def event(self, event_id):
            return NewsEvent(id=event_id, title="Грузоперевозки", published_at=None, sectors=[("49", 1.0)])

    app.dependency_overrides[optional_news] = TruckNews
    body = client.get("/api/companies/U_1/group-impact", params={"event_id": "src:news:t"}).json()
    assert body["affected"][0]["direct"] is True  # перевозчик группы — событие в его отрасли
    app.dependency_overrides[optional_news] = lambda: None
    assert client.get("/api/companies/U_1/group-impact", params={"event_id": "src:news:t"}).status_code == 503


def test_feed_marks_ready_insights(client):
    class Agent:
        llm = None  # без моделей дооценки нет

        def ready_events(self, event_ids, persona_id):
            return {e for e in event_ids if e == "src:news:rate"}

    app.dependency_overrides[news_provider] = FakeNews
    app.state.agent = Agent()
    try:
        items = client.get("/api/feed", params={"persona": "p-u1-cfo"}).json()["items"]
    finally:
        del app.state.agent
    assert items[0]["insight_ready"] is True
    # агента нет — неизвестно
    assert client.get("/api/feed", params={"persona": "p-u1-cfo"}).json()["items"][0]["insight_ready"] is None


class PictureNews(FakeNews):
    """Новости с картинкой, значком и полным текстом — как их сохранит парсер."""

    def events(self, since, limit):
        events = super().events(since, limit)
        for e in events:
            e.image_url, e.source_icon_url, e.text = (
                f"https://img/{e.id}.jpg",
                "https://ico/x.png",
                f"Текст {e.title}",
            )
        return events

    def event(self, event_id):
        return next((e for e in self.events(None, 10) if e.id == event_id), None)

    def search(self, query, limit):
        return [e for e in self.events(None, 10) if query.casefold() in e.title.casefold()][:limit]


def test_feed_items_have_takeaway_and_pictures(client):
    app.dependency_overrides[news_provider] = PictureNews
    item = client.get("/api/feed", params={"persona": "p-u1-cfo"}).json()["items"][0]
    assert item["takeaway"]["level"] in ("act", "watch", "info")
    assert 0 < len(item["takeaway"]["text"]) <= 160
    assert (item["image_url"], item["source_icon_url"]) == (
        "https://img/src:news:rate.jpg",
        "https://ico/x.png",
    )


def test_search_in_feed_format(client):
    app.dependency_overrides[news_provider] = PictureNews
    body = client.get("/api/search", params={"q": "ставка", "persona": "p-u1-cfo"}).json()
    assert [i["event_id"] for i in body["items"]] == ["src:news:rate"]
    assert body["items"][0]["relevance"]["score"] > 0
    # найденное, но не задевающее компанию — следом, с оценкой 0 и выводом «к сведению»
    gold = client.get("/api/search", params={"q": "золото", "persona": "p-u1-cfo"}).json()["items"][0]
    assert (gold["event_id"], gold["relevance"]["score"], gold["takeaway"]["level"]) == (
        "src:news:gold",
        0,
        "info",
    )
    assert gold["takeaway"]["text"] == "Напрямую вас не касается. Действий не нужно."
    assert client.get("/api/search", params={"q": "ставка", "persona": "p-u404-cfo"}).status_code == 404
    assert client.get("/api/search", params={"q": "с", "persona": "p-u1-cfo"}).status_code == 422


def test_event_detail(client):
    app.dependency_overrides[news_provider] = PictureNews
    body = client.get("/api/events/src:news:rate").json()
    assert (body["id"], body["text"], body["image_url"]) == (
        "src:news:rate",
        "Текст Ставка",
        "https://img/src:news:rate.jpg",
    )
    assert body["source"]["title"] == "Ставка"
    assert client.get("/api/events/src:news:нет").status_code == 404


def test_sources_catalog_and_connect(client):
    import api.main as main
    from api.sources import MemoryConnections, catalog_entries

    connections = MemoryConnections()
    app.dependency_overrides[main.get_connections] = lambda: connections
    catalog = client.get("/api/sources/catalog", params={"persona": "p-u1-cfo"}).json()
    names = [s["name"] for s in catalog]
    assert "Банк России" in names and names.count("Банк России") == 1  # две ленты — один источник
    cbr = next(s for s in catalog if s["name"] == "Банк России")
    assert (cbr["kind"], cbr["connected"], cbr["reliability"], cbr["country"]) == (
        "free",
        True,
        "official",
        "ru",
    )
    assert cbr["how_to_connect"]
    assert all(s["id"] != "minfin" for s in catalog)  # выключенная лента не предлагается
    first = catalog_entries()[0]["id"]
    done = client.post(f"/api/sources/{first}/connect", params={"persona": "p-u1-cfo"}).json()
    assert done["source"]["connected"] is True and done["message"]
    assert client.post("/api/sources/нет/connect", params={"persona": "p-u1-cfo"}).status_code == 404
    # вторая лента издателя ведёт к его записи в каталоге
    events = client.post("/api/sources/cbr-events/connect", params={"persona": "p-u1-cfo"}).json()
    assert events["source"]["id"] == cbr["id"]
    # пользователь должен быть действующим клиентом: отметки для несуществующих не пишутся
    assert client.post(f"/api/sources/{first}/connect", params={"persona": "p-u404-cfo"}).status_code == 404
    assert client.get("/api/sources/catalog", params={"persona": "p-u5-cfo"}).status_code == 404
    assert client.get("/api/sources/catalog", params={"persona": "кто-то"}).status_code == 404


def test_paid_source_is_connected_per_user(monkeypatch):
    import api.sources as sources

    feeds = [{"id": "paid-x", "publisher": "Платный сервис", "kind": "paid_api", "hosts": ["paid.com"]}]
    monkeypatch.setattr(sources, "_feeds", lambda: feeds)
    connections = sources.MemoryConnections()
    entry = sources.catalog(connections, "p-u1-cfo")[0]
    assert (entry.kind, entry.country, entry.connected) == ("paid_api", "intl", False)
    assert any("SOURCE_PAID_X_API_KEY" in step for step in entry.how_to_connect)
    connections.connect("p-u1-cfo", "paid-x")
    assert sources.catalog(connections, "p-u1-cfo")[0].connected is True
    assert sources.catalog(connections, "p-u2-cfo")[0].connected is False


def test_snapshot_search(tmp_path):
    import json

    from api.news import SnapshotNews

    path = tmp_path / "news.jsonl"
    rows = [
        {
            "id": "src:news:a",
            "title": "Ключевая ставка сохранена",
            "published_at": "2026-10-23T10:00:00+03:00",
        },
        {
            "id": "src:news:b",
            "title": "Курс рубля",
            "fragment": "ставка ЦБ",
            "published_at": "2026-10-22T10:00",
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    news = SnapshotNews(path)
    assert [e.id for e in news.search("ставка", 10)] == ["src:news:a", "src:news:b"]
    assert [e.id for e in news.search("ключевая ставка", 10)] == ["src:news:a"]
    assert news.search("", 10) == []


def test_catalog_from_parser_catalog(monkeypatch):
    import api.sources as sources

    rows = [
        {
            "id": "reuters",
            "name": "Reuters",
            "country": "intl",
            "kind": "paid_api",
            "reliability": "agency",
            "topics": ["рынки"],
            "how_to_connect": ["Получите ключ.", "Перезапустите парсер."],
            "docs_url": None,
            "icon_url": None,
            "note": "только по подписке",
            "key_env": "REUTERS_API_KEY",
            "feeds": [],
            "connected": False,
        },
        {
            "id": "cbr",
            "name": "Банк России",
            "country": "ru",
            "kind": "free",
            "reliability": "official",
            "topics": [],
            "how_to_connect": [],
            "docs_url": None,
            "icon_url": None,
            "note": None,
            "key_env": None,
            "feeds": ["cbr-press", "cbr-events"],
            "connected": True,
        },
    ]
    monkeypatch.setattr(sources, "_parser_catalog", lambda: rows)
    connections = sources.MemoryConnections()
    entries = sources.catalog(connections, "p-u1-cfo")
    assert [e.id for e in entries] == ["cbr", "reuters"]  # подключённые — первыми
    assert entries[1].note == "только по подписке" and entries[1].connected is False
    assert sources.entry_id("cbr-events") == "cbr"
    message = sources.connect_message(rows[0])
    assert "REUTERS_API_KEY" in message and message.endswith("Перезапустите парсер.")
