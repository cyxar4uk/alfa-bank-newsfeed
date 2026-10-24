import datetime as dt

import pytest
from factories import make_company
from pydantic import ValidationError

from api.chain import build_chain
from api.exposure import build_exposure
from api.ranking import (
    MSK,
    NewsEvent,
    RankingConfig,
    default_ranking,
    event_from,
    freshness,
    rank,
    score_event,
)
from api.records import Flow

NOW = dt.datetime(2026, 10, 24, 12, tzinfo=MSK)
YESTERDAY = NOW - dt.timedelta(days=1)

# оптовик топливом: кредит, лизинг, депозитов нет, ВЭД; без группы, чтобы считать просто
COMPANY = make_company(group_id=None, deposit=True, revenue=5e9)
CAFE = make_company(id="U_10", okved_code="56.10", group_id=None)
FLOWS = [Flow("U_10", "in", 1e9, 10, CAFE), Flow("U_99", "out", 1e9, 5, None)]


def news(event_id, factors=(), sectors=(), days=1, publisher="Интерфакс"):
    return NewsEvent(
        id=event_id if event_id.startswith("src:") else f"src:news:{event_id}",
        title=f"Новость {event_id}",
        published_at=NOW - dt.timedelta(days=days),
        publisher=publisher,
        factors=[(code, strength, code) for code, strength in factors],
        sectors=list(sectors),
    )


RATE = news("src:news:rate", factors=[("rate", 1.0)])
DEPOSIT = news("src:news:deposit", factors=[("deposit_yield", 1.0)])
CAFES = news("src:news:cafes", sectors=[("56", 1.0)])
UNRELATED = news("src:news:gold", factors=[("commodity_gold", 1.0)])


def feed(events, role, company=COMPANY, flows=FLOWS, **kwargs):
    exposure = build_exposure(company, flows, [])
    return rank(events, exposure, lambda o, w: build_chain(company, flows, [], o, w), role, NOW, **kwargs)


def test_role_changes_order_and_shows_weight():
    cfo = feed([RATE, DEPOSIT], "cfo")
    treasury = feed([RATE, DEPOSIT], "treasury")
    assert [i.event_id for i in cfo] == ["src:news:rate", "src:news:deposit"]
    assert [i.event_id for i in treasury] == ["src:news:deposit", "src:news:rate"]
    weights = {i.event_id: i.relevance.breakdown[0].role_weight for i in cfo}
    assert weights == {"src:news:rate": 1.6, "src:news:deposit": 1.1}


def test_breakdown_sums_to_score():
    item = feed([news("x", factors=[("rate", 0.8), ("fx", 0.5)], sectors=[("56", 1.0)])], "cfo")[0]
    terms = item.relevance.breakdown
    assert {t.kind for t in terms} == {"factor", "chain"}
    assert sum(t.value for t in terms) == pytest.approx(item.relevance.score, abs=1e-3)
    rate = next(t for t in terms if t.code == "rate")
    assert (rate.event_strength, rate.exposure, rate.role_weight) == (0.8, 0.7, 1.6)
    assert item.relevance.refs[0] == "feat:customer_sectors"  # главный вклад — покупатели-кафе
    assert item.relevance.refs[-1] == "src:news:x"


def test_event_through_buyers_industry_company_does_not_have():
    # событие про общепит: у оптовика топливом своей такой отрасли нет, но покупатели — кафе
    item = feed([CAFES], "ceo")[0]
    assert item.channel == "buyers"
    assert item.channel_text.startswith("событие → гостиницы и общепит (56) → ваши покупатели")
    assert item.relevance.breakdown[0].code == "chain:buyers:56"
    assert item.relevance.breakdown[0].role_weight == 1.4  # гендиректору покупатели важнее


def test_unrelated_event_is_not_in_feed():
    assert feed([UNRELATED], "cfo") == []
    assert feed([news("empty")], "cfo") == []


def test_aliases_from_news_tagging():
    item = feed([news("oil", factors=[("commodity_oil_gas", 1.0)])], "owner")[0]
    assert item.factors[0].code == "commodity_oil"
    assert item.factors[0].label == "Сырьё: нефть, газ и топливо"


def test_freshness_and_source_quality():
    scoring = default_ranking().scoring
    assert freshness(NOW, NOW, scoring) == 1.0
    assert freshness(NOW - dt.timedelta(days=14), NOW, scoring) == pytest.approx(0.5)
    assert freshness(NOW - dt.timedelta(days=400), NOW, scoring) == scoring.min_freshness
    assert freshness(None, NOW, scoring) == scoring.min_freshness
    fresh, old = feed([RATE, news("old", factors=[("rate", 1.0)], days=30)], "cfo")
    assert fresh.event_id == RATE.id
    assert old.relevance.freshness < fresh.relevance.freshness
    unknown = feed([news("blog", factors=[("rate", 1.0)], publisher="Блог")], "cfo")[0]
    assert unknown.relevance.source_quality == 0.9


def test_bank_view_bonus_is_a_term():
    item = feed([RATE], "cfo", bank_view=lambda codes: True)[0]
    bank = item.relevance.breakdown[-1]
    assert (bank.kind, bank.value) == ("bank", 0.05)
    assert item.has_bank_view is True
    assert sum(t.value for t in item.relevance.breakdown) == pytest.approx(item.relevance.score, abs=1e-3)


def test_repeated_reason_is_penalised_in_breakdown():
    events = [news(f"rate{i}", factors=[("rate", 1.0)]) for i in range(3)]
    items = feed(events, "cfo")
    assert [t.kind for t in items[2].relevance.breakdown][-1] == "repeat"
    assert items[2].relevance.score < items[0].relevance.score
    for item in items:
        assert sum(t.value for t in item.relevance.breakdown) == pytest.approx(item.relevance.score, abs=1e-3)


def test_event_from_snapshot_dict_and_object():
    raw = {
        "id": "src:news:1",
        "title": "Ставка",
        "published_at": "2026-10-23T10:00:00+03:00",
        "publisher": "Банк России",
        "tags": {
            "factors": [{"code": "rate", "name": "ставка", "strength": 0.9}],
            "sector_links": [{"okved": "64", "name": "финансы", "strength": 0.5, "via": "text"}],
            "okved": ["64"],
        },
    }
    event = event_from(raw)
    assert (event.factors, event.sectors) == ([("rate", 0.9, "ставка")], [("64", 0.5)])
    assert event.published_at.tzinfo is not None

    class Item:  # как NewsItem из базы поиска: разметка — атрибутами
        id, title, published_at, publisher, url, fragment = "src:news:2", "Курс", None, None, None, None
        tags = None
        factors = [type("F", (), {"code": "fx", "strength": 0.4, "name": "курс"})()]
        sector_links = []

    assert event_from(Item()).factors == [("fx", 0.4, "курс")]


def test_score_event_requires_exposure():
    exposure = build_exposure(COMPANY, FLOWS, [])
    assert score_event(UNRELATED, exposure, lambda o, w: None, "cfo", NOW) is None


def test_roles_config_validation():
    config = default_ranking()
    assert set(config.roles) == {"owner", "ceo", "cfo", "chief_accountant", "treasury", "other"}
    assert config.roles["owner"].weight("commodity_metals") == 1.2  # по префиксу commodity_*
    assert config.roles["other"].weight("rate") == 1.0
    with pytest.raises(ValidationError):
        RankingConfig.model_validate({"version": "t", "roles": {"intern": {"label": "x", "focus": "x"}}})
    with pytest.raises(ValidationError):
        RankingConfig.model_validate({"version": "t", "roles": {}, "scorring": {}})


def test_same_basis_counted_once():
    # оптовик топливом, новость про нефть с отраслью 46: «своя отрасль» в карте и в цепочке — одно основание
    oil = news("oil46", factors=[("commodity_oil_gas", 1.0)], sectors=[("46", 1.0)])
    item = feed([oil], "owner")[0]
    kinds = [t.code for t in item.relevance.breakdown]
    assert ("commodity_oil" in kinds) != ("chain:direct:46" in kinds)  # ровно одно из двух
    # покупатели-кафе: фактор «потребительский спрос через покупателей» и канал цепочки по 56 — тоже одно
    cafes = news("cafes2", factors=[("consumer", 1.0)], sectors=[("56", 1.0)])
    codes = [t.code for t in feed([cafes], "ceo")[0].relevance.breakdown]
    assert ("consumer" in codes) != ("chain:buyers:56" in codes)


def test_region_factor_only_for_company_region():
    moscow = make_company(
        group_id=None, region="Москва", city="г. Москва", okved_code="62.01", fts_flag=False
    )
    exposure = build_exposure(moscow, [], [])
    kamchatka = news("quake", factors=[("region", 1.0)])
    kamchatka.tags.regions = ["Камчатский край"]
    local = news("moscow", factors=[("region", 1.0)])
    local.tags.regions = ["Москва"]
    items = rank([kamchatka, local], exposure, lambda o, w: None, "ceo", NOW, regions={"Москва", "г. Москва"})
    assert [i.event_id for i in items] == ["src:news:moscow"]


def test_bank_bonus_does_not_lift_irrelevant_event():
    # слабое совпадение ниже порога не становится релевантным из-за аналитики банка
    weak = news("weak", factors=[("labor", 0.01)])
    assert feed([weak], "cfo", bank_view=lambda codes: True) == []
    item = feed([RATE], "cfo", bank_view=lambda codes: codes == ["rate"])[0]
    assert (
        item.relevance.breakdown[-1].label == "есть аналитика Альфа-Банка по фактору: стоимость заёмных денег"
    )


def test_dates_without_timezone():
    assert event_from(
        {"id": "src:news:a", "title": "x", "published_at": "2026-10-23T10:00:00"}
    ).published_at.tzinfo
    assert event_from({"id": "src:news:b", "title": "x", "published_at": "2026-10-23"}).published_at.tzinfo
    assert event_from({"id": "src:news:c", "title": "x", "published_at": "вчера"}).published_at is None


def test_repeat_label_plural():
    from api.ranking import _times

    assert [_times(n) for n in (1, 2, 5, 12, 22)] == ["1 раз", "2 раза", "5 раз", "12 раз", "22 раза"]
