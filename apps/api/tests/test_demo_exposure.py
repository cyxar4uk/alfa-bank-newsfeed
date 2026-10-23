"""Карты демо-клиентов на настоящих данных кейса — сверка с ожидаемыми картами сценария проверки.

Запускается, если задан DEMO_DATABASE_URL — база с загруженными данными кейса (только чтение).
"""

import os

import pytest

URL = os.environ.get("DEMO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="DEMO_DATABASE_URL не задан")

# ожидаемая сила факторов: high / medium / low / none / no_data
EXPECTED = {
    "U_8318": {  # оптовик автозапчастей, импорт через группу
        "fx": "high",
        "rate": "high",
        "consumer": "high",
        "ved_logistics": "medium",
        "supply_45": "medium",
        "demand_45": "low",
        "labor": "medium",
        "inflation": "medium",
        "gov": "none",
        "deposit_yield": "none",
    },
    "U_57706": {  # топливный оптовик в холдинге, платежей < 1 % выручки
        "commodity_oil": "high",
        "deposit_yield": "high",
        "gov": "high",
        "rate": "medium",
        "fx": "medium",
        "ved_logistics": "low",
        "labor": "low",
        "demand": "no_data",
        "supply": "no_data",
    },
    "U_34911": {  # зернотрейдер-экспортёр
        "fx": "high",
        "commodity_agro": "high",
        "ved_logistics": "high",
        "rate": "high",
        "inflation": "medium",
        "commodity_oil": "medium",
        "region": "medium",
        "demand": "no_data",
        "supply_46": "low",
        "labor": "low",
        "gov": "none",
        "deposit_yield": "none",
    },
    "U_258116": {  # поставщик общепита, цепочка через покупателей
        "demand_56": "high",
        "consumer": "high",
        "fx": "high",
        "labor": "medium",
        "supply_52": "medium",
        "rate": "medium",
        "ved_logistics": "medium",
        "inflation": "medium",
        "gov": "none",
        "deposit_yield": "none",
    },
}


@pytest.fixture(scope="module")
def repo():
    from psycopg_pool import ConnectionPool

    from api.repo import PgCompanyRepo

    with ConnectionPool(URL, min_size=1, max_size=2) as pool:
        yield PgCompanyRepo(pool)


def exposure(repo, company_id):
    from api.exposure import build_exposure

    company = repo.get_company(company_id)
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    return build_exposure(company, repo.flows(company.id), group)


@pytest.mark.parametrize("company_id", list(EXPECTED))
def test_demo_client_map(repo, company_id):
    levels = {f.code: f.level for f in exposure(repo, company_id).factors}
    assert {code: levels.get(code) for code in EXPECTED[company_id]} == EXPECTED[company_id]


def test_all_large_companies(repo):
    for company in repo.list_companies(large=True, limit=500, offset=0):
        result = exposure(repo, company.id)
        assert result.factors
        for factor in result.factors:
            if factor.level in ("high", "medium"):
                assert factor.evidence and factor.channel, (company.id, factor.code)
            if factor.code.startswith(("demand_", "supply_")):
                assert factor.coverage is not None, (company.id, factor.code)


def chain(repo, company_id, okved):
    from api.service import company_chain

    return {(c.kind, c.okved): c for c in company_chain(repo, company_id, okved).channels}


def test_demo_chains_match_manual_csv_count(repo):
    # поставщик общепита: 53,1 % внешних поступлений — от ОКВЭД 56, покрытие 66 % (расчёт по CSV)
    buyers = chain(repo, "U_258116", ["56"])[("buyers", "56")]
    assert round(buyers.share, 3) == 0.531
    assert round(buyers.coverage, 2) == 0.66
    # оптовик автозапчастей: 50,9 % внешних платежей — ОКВЭД 45; импортёры группы — отдельно, в канале группы
    channels = chain(repo, "U_8318", ["45"])
    assert round(channels[("suppliers", "45")].share, 3) == 0.509
    assert {"U_92457", "U_52177"} <= {n.id for n in channels[("group", "45")].nodes}
    assert not {"U_92457", "U_52177"} & {n.id for n in channels[("suppliers", "45")].nodes}
    # топливный оптовик из Уфы: половина поступлений — от строителя дорог (42), один плательщик U_196945
    road = chain(repo, "U_26030", ["42"])[("buyers", "42")]
    assert round(road.share, 3) == 0.506
    assert road.nodes[0].id == "U_196945"
