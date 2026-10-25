import datetime as dt

from fastapi.testclient import TestClient
from test_api import FakeRepo
from test_takeaway import exposure_map, item
from test_week import DAYS, dated, event

from api.contract import ExposureChannel, ExposureMap, FactorExposure
from api.main import app, get_repo, news_provider
from api.ranking import MSK, default_ranking
from api.riskmap import limits, now_for, order, why


def factor(code, strength, level, text="", estimate=False):
    return FactorExposure(
        id=f"exp:{code}",
        code=code,
        label=code,
        strength=strength,
        level=level,
        channel=ExposureChannel(kind="direct", text=text) if text else None,
        estimate=estimate,
    )


def test_order_follows_role_weights():
    exposure = ExposureMap(
        company_id="U_1",
        catalog_version="t",
        levels=[],
        factors=[
            factor("rate", 0.6, "high"),
            factor("gov", 0.65, "high"),
            factor("fx", 0.45, "medium"),
            factor("labor", 0.0, "none"),
            factor("demand", None, "no_data"),
        ],
    )
    config = default_ranking()
    cfo = [f.code for f in order(exposure, "cfo", config)]
    assert cfo[0] == "rate" and set(cfo) == {"rate", "gov", "fx"}  # финдиректору ставка важнее; нулевых нет
    assert [f.code for f in order(exposure, "owner", config)][0] == "gov"  # собственнику — госрасходы
    assert limits(exposure, 0.007) == [
        "Не оцениваем спрос покупателей и поставщиков: платежи в выгрузке покрывают 0,7 % выручки,"
        " цепочки через контрагентов не строим.",
        "Нет данных, чтобы оценить: demand.",
    ]


def test_why_is_plain():
    oil = factor(
        "commodity_oil",
        0.8,
        "high",
        "своя отрасль — нефть, газ и топливо: 46.71 Торговля оптовая твердым, жидким и газообразным топливом",
    )
    assert (
        why(oil)
        == "Ваша отрасль — нефть, газ и топливо: торговля оптовая твердым, жидким и газообразным топливом."
    )
    fx = factor(
        "fx",
        0.45,
        "medium",
        "ВЭД со странами ЕАЭС: Киргизия, Казахстан; направление — экспорт (оценка по отрасли)",
    )
    assert why(fx) == "ВЭД со странами ЕАЭС: Киргизия, Казахстан."


def test_now_is_the_latest_news_of_the_week():
    exposure = exposure_map()
    held = dated(item(0.6, title="ЦБ сохранил ставку 14 %"), 4, "held")
    vague = dated(item(0.5, title="Набиуллина о кредитах"), 5, "vague")
    assert (
        now_for([held, vague], "rate", exposure)[0].event_id == "src:news:vague"
    )  # последняя — даже без направления
    assert now_for([vague], "rate", exposure)[1] == "Новое"
    assert now_for([held], "rate", exposure)[1] == "Держится"
    assert now_for([held], "fx", exposure) is None


class WeekNews:
    name = "тест"

    def __init__(self):
        self.list = [
            event("rate", 6, [("rate", 1.0)]),
            event("rate2", 4, [("rate", 1.0)]),
            event("gold", 5, [("commodity_gold", 1.0)]),
        ]
        for e in self.list:
            e.title = "ЦБ сохранил ставку 14 %" if e.id.startswith("src:news:rate") else "Золото дорожает"

    def events(self, since, limit):
        return [e for e in self.list if since is None or e.published_at >= since][:limit]

    def has_bank_view(self, factors):
        return False

    def bank_fragments(self, factors, query=""):
        return []


def test_endpoints(monkeypatch):
    import api.main as main

    now = dt.datetime.combine(DAYS[-1], dt.time(12), tzinfo=MSK)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(main.dt, "datetime", Clock)
    app.dependency_overrides[get_repo] = FakeRepo
    app.dependency_overrides[news_provider] = WeekNews
    try:
        client = TestClient(app)
        week = client.get("/api/briefing", params={"persona": "p-u1-cfo", "period": "week"}).json()
        assert week["period"] == "week" and len(week["week"]) == 7
        story = week["stories"][0]
        assert story["code"] == "rate" and story["daily_counts"][-1] == 1 and story["news_count"] == 2
        assert story["takeaway"]["text"] and week["action"]["code"] == "rate"
        day = client.get("/api/briefing", params={"persona": "p-u1-cfo"}).json()
        assert day["period"] == "day" and day["stories"] == []

        risk = client.get("/api/companies/U_1/risk-map", params={"persona": "p-u1-cfo"}).json()
        assert risk["role"] == "cfo" and 1 <= len(risk["factors"]) <= 7
        rate = next(f for f in risk["factors"] if f["code"] == "rate")
        assert rate["strength"] == "strong" and rate["now"]["direction"] == "Держится"
        assert rate["week_counts"][-1] == 1 and rate["news_count"] == 2
        # пользователь чужой компании — нет
        assert client.get("/api/companies/U_4/risk-map", params={"persona": "p-u1-cfo"}).status_code == 404
    finally:
        app.dependency_overrides.clear()
