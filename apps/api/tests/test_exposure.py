import pytest
from factories import make_company
from pydantic import ValidationError

from api.exposure import CATALOG_PATH, Catalog, build_exposure, default_catalog, direction, load_catalog
from api.records import Flow


def flow(cp, direction, amount, counterparty=None, payments=1):
    return Flow(cp, direction, amount, payments, counterparty)


def by_code(exposure):
    return {f.code: f for f in exposure.factors}


# оптовик топливом: кредит, лизинг, зарплатный проект, ВЭД с Китаем, ОАЭ и Кореей, группа group_1_sb
BASE = make_company()
NO_GROUP = dict(group_id=None)


def test_full_catalog_loads():
    catalog = default_catalog()
    assert catalog.version
    codes = {f.code for f in catalog.factor}
    # все факторы из каталога спецификации, кроме спроса и поставок — они строятся по классам ОКВЭД
    assert {
        "rate",
        "deposit_yield",
        "fx",
        "ved_logistics",
        "consumer",
        "labor",
        "gov",
        "commodity_oil",
        "commodity_metals",
        "commodity_gold",
        "commodity_fertilizers",
        "commodity_agro",
        "inflation",
        "region",
    } <= codes
    assert {d.prefix for d in catalog.dynamic} == {"demand", "supply"}


def test_own_signals_strength_channel_and_evidence():
    exposure = build_exposure(BASE, flows=[])
    f = by_code(exposure)

    assert f["rate"].level == "high"
    assert f["rate"].channel.kind == "direct"
    # канал — от сильнейшего сигнала, остальные заметные дописаны
    assert f["rate"].channel.text == "собственный кредит в банке; также лизинг в банке"
    # доказательства от всех сработавших сигналов: кредит и лизинг
    assert [e.ref for e in f["rate"].evidence] == ["feat:CL_PRODUCT_LOA_MARK", "feat:CL_PRODUCT_LEA_MARK"]
    assert f["commodity_oil"].level == "high"
    assert f["deposit_yield"].level == "none"  # депозитов нет
    assert f["deposit_yield"].strength == 0
    # направление ВЭД — оценка по отрасли, помечено
    assert f["fx"].estimate is True
    assert "направление — экспорт (оценка по отрасли)" in f["fx"].channel.text
    assert f["fx"].channel.text.count("оценка по отрасли") == 1
    assert any("оценка по отрасли" in w for w in exposure.warnings)
    # каждый фактор от средней силы — с доказательствами и каналом
    for factor in exposure.factors:
        if factor.level in ("high", "medium"):
            assert factor.evidence and factor.channel and factor.channel.text


def test_factors_sorted_by_level_and_strength():
    exposure = build_exposure(BASE, flows=[])
    order = {"high": 0, "medium": 1, "low": 2, "no_data": 3, "none": 4}
    keys = [(order[f.level], -(f.strength or 0)) for f in exposure.factors]
    assert keys == sorted(keys)


def test_no_payments_means_no_data_not_zero():
    exposure = build_exposure(make_company(**NO_GROUP), flows=[])
    f = by_code(exposure)
    assert f["demand"].level == "no_data"
    assert f["demand"].strength is None
    assert f["demand"].notes == ["нет платежей в выгрузке"]
    assert f["supply"].level == "no_data"
    assert "платежей в выгрузке нет — спрос и поставки не оцениваем" in exposure.warnings


def test_payments_far_below_revenue_mean_no_data():
    # оборот 0,5 % выручки — как у топливного холдинга: цепочки не строим
    cafe = make_company(id="U_10", okved_code="56.10", **NO_GROUP)
    exposure = build_exposure(make_company(**NO_GROUP), [flow("U_10", "in", 1e8, cafe)])
    f = by_code(exposure)
    assert f["demand"].level == "no_data"
    assert "0,5 % выручки" in f["demand"].notes[0]
    assert f["consumer"].level == "none"  # сигнал по покупателям не срабатывает без данных


def test_demand_by_okved_with_coverage():
    company = make_company(revenue=5e9, **NO_GROUP)
    cafe = make_company(id="U_10", okved_code="56.10", **NO_GROUP)
    canteen = make_company(id="U_11", okved_code="56.29", **NO_GROUP)
    shop = make_company(id="U_12", okved_code="47.11", **NO_GROUP)
    flows = [
        flow("U_10", "in", 3e8, cafe),
        flow("U_11", "in", 2e8, canteen),
        flow("U_12", "in", 1e8, shop),
        flow("U_99", "in", 4e8),  # неизвестный плательщик
    ]
    f = by_code(build_exposure(company, flows))

    demand = f["demand_56"]
    assert demand.level == "high"  # 50 % поступлений
    assert demand.channel.kind == "buyers"
    assert demand.coverage == 0.6
    assert demand.okved == "56"
    assert "гостиницы и общепит (56) — 50 % поступлений, 2 плательщиков" in demand.channel.text
    assert f["demand_47"].level == "low"  # 10 %
    # потребительский спрос через покупателей: 56 + 47 = 60 %
    assert f["consumer"].level == "high"
    assert f["consumer"].channel.kind == "buyers"
    assert f["supply"].level == "no_data"  # платежей поставщикам нет


def test_low_coverage_caps_strength():
    company = make_company(revenue=5e9, **NO_GROUP)
    cars = make_company(id="U_10", okved_code="45.31", **NO_GROUP)
    flows = [flow("U_10", "in", 2e8, cars), flow("U_99", "in", 8e8)]  # отрасль известна у 20 %
    f = by_code(build_exposure(company, flows))
    assert f["demand_45"].strength == 0.29
    assert f["demand_45"].level == "low"
    assert f["demand_45"].notes == ["сила ограничена: отрасль известна лишь у 20 % суммы"]


def test_unknown_counterparties_only():
    company = make_company(revenue=5e9, **NO_GROUP)
    exposure = build_exposure(company, [flow("U_98", "out", 3e8), flow("U_99", "out", 2e8)])
    supply = by_code(exposure)["supply"]
    assert supply.level == "none"
    assert supply.coverage == 0
    assert "отрасль известна у 0 % суммы" in supply.notes[0]
    assert "отрасль известна лишь у 0 % внешних платежей поставщикам" in exposure.warnings


def test_no_foreign_trade():
    company = make_company(fts_flag=False, fts_countries=None, **NO_GROUP)
    exposure = build_exposure(company, flows=[])
    f = by_code(exposure)
    assert f["fx"].level == "none"
    assert f["ved_logistics"].level == "none"
    assert not any("ВЭД" in w for w in exposure.warnings)


def test_eaeu_only_is_weaker():
    company = make_company(fts_countries="КАЗАХСТАН, КИРГИЗИЯ", **NO_GROUP)
    f = by_code(build_exposure(company, flows=[]))
    assert f["fx"].level == "medium"
    assert f["ved_logistics"].level == "low"


def test_group_signals():
    company = make_company(okved_code="46.71", credit=False, leasing=False, factoring=False)
    builders = [
        make_company(id=f"U_{i}", okved_code="42.11", revenue=10e9, credit=i < 23, fts_flag=False)
        for i in range(20, 24)
    ]
    retail = make_company(id="U_30", okved_code="47.11", revenue=30e9, credit=False, fts_flag=False)
    f = by_code(build_exposure(company, flows=[], group=[*builders, retail]))

    # стройка — 40 из 70 млрд выручки группы
    assert f["gov"].level == "high"
    assert f["gov"].channel.kind == "group"
    assert "57 % выручки группы" in f["gov"].channel.text
    assert f["gov"].evidence[0].ref == "feat:GROUP_ID"
    # кредиты у трёх компаний группы
    assert (
        f["rate"].channel.text == "капиталоёмкие компании группы (стройка, генерация) — 57 % выручки группы;"
        " также кредиты у 3 из 5 других компаний группы"
    )
    assert any(e.value == "3 из 5" for e in f["rate"].evidence)


def test_group_importers_drive_fx():
    company = make_company(okved_code="45.31.1", fts_flag=False, fts_countries=None)
    importer = make_company(id="U_50", okved_code="45.31", fts_flag=True, fts_countries="КИТАЙ, ОАЭ")
    outsider = make_company(id="U_60", okved_code="45.31", group_id="group_x", fts_flag=False)
    flows = [flow("U_50", "out", 4e9, importer), flow("U_60", "out", 6e9, outsider)]
    f = by_code(build_exposure(company, flows, group=[importer]))
    assert f["fx"].level == "high"  # 40 % платежей — импортёру группы
    assert f["fx"].estimate is True
    assert f["fx"].channel.kind == "group"
    assert "40 % всех платежей идут 1 компаниям группы (Китай, ОАЭ)" in f["fx"].channel.text
    assert f["fx"].evidence[0].ref == "feat:intra_group_share"
    # импортёр группы не попадает во внешних поставщиков
    assert "supply_45" in f and "40 %" not in f["supply_45"].channel.text


def test_new_factor_from_config_without_code(tmp_path):
    text = CATALOG_PATH.read_text("utf-8") + (
        "\n[[factor]]\n"
        'code = "climate"\n'
        'label = "Погода и климат"\n'
        "[[factor.signal]]\n"
        'kind = "own_okved"\n'
        'codes = ["46.71"]\n'
        "strength = 0.5\n"
        'text = "топливо: спрос зависит от погоды"\n'
    )
    path = tmp_path / "factors.toml"
    path.write_text(text, "utf-8")
    climate = by_code(build_exposure(BASE, flows=[], catalog=load_catalog(path)))["climate"]
    assert (climate.label, climate.level, climate.channel.text) == (
        "Погода и климат",
        "medium",
        "топливо: спрос зависит от погоды",
    )


@pytest.mark.parametrize(
    "signal",
    [
        '{ kind = "flag", field = "nonexistent", strength = 0.5, text = "x" }',
        '{ kind = "side_share", side = "customers", okved = ["56"], text = "x" }',  # нет thresholds
        '{ kind = "own_okved", codes = ["46"], text = "x" }',  # нет strength
        '{ kind = "telepathy", strength = 0.5, text = "x" }',
        '{ kind = "region", regoins = ["Москва"], strength = 0.3, text = "x" }',  # опечатка в поле
        '{ kind = "group_okved", codes = ["41"], strength = 0.5, text = "x" }',  # нет min_revenue_share
        '{ kind = "side_share", side = "customers", okved = ["56"], thresholds = [[0.1, 1.5]], text = "x" }',
        '{ kind = "side_share", side = "customers", okved = ["46.2"], thresholds = [[0.1, 0.5]],'
        ' text = "x" }',
        '{ kind = "workers", strength = 0.3, text = "x" }',  # нет values
        '{ kind = "own_okved", codes = ["46"], strength = 0.5, text = "{share" }',  # битый шаблон
        '{ kind = "own_okved", codes = ["46"], strength = 0.5, text = "{shrae}" }',  # неизвестная подстановка
        '{ kind = "own_okved", codes = ["46"], strength = 0.5, text = "{share:.1f}" }',  # формат
        '{ kind = "own_okved", codes = ["4"], strength = 0.5, text = "x" }',  # не код ОКВЭД
    ],
)
def test_bad_catalog_is_rejected(signal):
    import tomllib

    raw = tomllib.loads(f'version = "t"\n[[factor]]\ncode = "x"\nlabel = "X"\nsignal = [{signal}]\n')
    with pytest.raises(ValidationError):
        Catalog.model_validate(raw)


def test_catalog_level_rules():
    always = {"kind": "always", "strength": 0.1, "text": "x"}
    dynamic = {
        "prefix": "demand",
        "side": "customers",
        "label": "x",
        "channel": "buyers",
        "min_share": 0.05,
        "thresholds": [[0.5, 0.7]],
        "text": "x",
    }
    with pytest.raises(ValidationError):  # порядок порогов
        Catalog.model_validate({"version": "t", "levels": {"high": 0.3, "medium": 0.6}})
    with pytest.raises(ValidationError):  # код совпадает с динамическим фактором
        Catalog.model_validate(
            {
                "version": "t",
                "dynamic": [dynamic],
                "factor": [{"code": "demand_56", "label": "x", "signal": [always]}],
            }
        )
    with pytest.raises(ValidationError):  # лишний ключ верхнего уровня
        Catalog.model_validate({"version": "t", "levles": 1})
    # а правильный — загружается
    assert Catalog.model_validate({"version": "t", "dynamic": [dynamic]}).dynamic[0].prefix == "demand"


def test_evidence_refs_are_profile_features():
    company = make_company(revenue=5e9)
    cafe = make_company(id="U_10", okved_code="56.10", group_id=None)
    importer = make_company(id="U_50", okved_code="45.31", fts_countries="КИТАЙ")
    builders = [make_company(id=f"U_{i}", okved_code="42.11", revenue=10e9) for i in range(20, 24)]
    flows = [flow("U_10", "in", 1e9, cafe), flow("U_50", "out", 5e8, importer), flow("U_99", "out", 5e8)]
    exposure = build_exposure(company, flows, group=[importer, *builders])
    refs = {e.ref for f in exposure.factors for e in f.evidence}
    assert refs and all(r.startswith("feat:") for r in refs)
    assert {"feat:customer_sectors", "feat:GROUP_ID", "feat:intra_group_share"} <= refs
    assert all(f.id == f"exp:{f.code}" for f in exposure.factors)
    demand = by_code(exposure)["demand_56"]
    assert demand.evidence[0].label == "Внешние поступления от контрагентов с ОКВЭД 56"


def test_foreign_trade_without_countries_is_medium_not_high():
    f = by_code(build_exposure(make_company(fts_countries=None, **NO_GROUP), flows=[]))
    assert f["fx"].level == "medium"
    assert (
        f["fx"].channel.text
        == "ВЭД есть, страны в данных не указаны; направление — экспорт (оценка по отрасли)"
    )
    assert f["ved_logistics"].level == "low"


def test_unknown_direction_is_not_called_estimate():
    company = make_company(okved_code="62.01", fts_countries="КИТАЙ", **NO_GROUP)
    exposure = build_exposure(company, flows=[])
    fx = by_code(exposure)["fx"]
    assert "направление — в данных не указано" in fx.channel.text
    assert fx.estimate is False
    assert not any("оценка по отрасли" in w for w in exposure.warnings)


def test_group_importer_fx_warns_about_estimate():
    company = make_company(okved_code="45.31.1", fts_flag=False, fts_countries=None)
    importer = make_company(id="U_50", okved_code="45.31", fts_flag=True, fts_countries="КИТАЙ")
    exposure = build_exposure(company, [flow("U_50", "out", 4e9, importer)], group=[importer])
    assert "направления ВЭД в данных нет: «импорт» — оценка по отрасли" in exposure.warnings


def test_concentration_warning():
    company = make_company(revenue=5e9, **NO_GROUP)
    cafe = make_company(id="U_10", okved_code="56.10", **NO_GROUP)
    flows = [flow("U_99", "in", 6e8), flow("U_10", "in", 4e8, cafe)]
    exposure = build_exposure(company, flows)
    assert (
        "ваш крупнейший покупатель — 60 % внешних поступлений (вне данных банка):"
        " зависимость от одного контрагента" in exposure.warnings
    )


def test_inflation_is_never_none():
    f = by_code(build_exposure(make_company(okved_code="62.01", **NO_GROUP), flows=[]))
    assert f["inflation"].level == "low"


def test_direction_longest_prefix():
    catalog = default_catalog()
    assert direction(make_company(okved_code="46.21"), catalog) == "экспорт"
    assert direction(make_company(okved_code="46.90"), catalog) == "импорт"
    assert direction(make_company(okved_code="62.01"), catalog) is None
    # 46.22 — опт цветами, не зерно: в экспорт не записываем
    assert direction(make_company(okved_code="46.22"), catalog) == "импорт"


def test_levels():
    catalog = default_catalog()
    assert [catalog.level(x) for x in (0.6, 0.59, 0.3, 0.29, 0.01, 0.0, None)] == [
        "high",
        "medium",
        "medium",
        "low",
        "low",
        "none",
        "no_data",
    ]


def test_levels_are_defined_in_api():
    levels = {x.level: x for x in build_exposure(BASE, flows=[]).levels}
    assert list(levels) == ["high", "medium", "low", "none", "no_data"]
    assert (levels["high"].min, levels["high"].max) == (0.6, None)
    assert (levels["medium"].min, levels["medium"].max) == (0.3, 0.6)
    assert (levels["low"].min, levels["low"].max) == (0.01, 0.3)  # ноль — уровень none
    assert levels["high"].meaning.startswith("сильная прямая связь")
    assert all(x.meaning for x in levels.values())


def test_inflation_is_strong_for_food_and_fuel_trade():
    for okved in ("46.71", "47.11", "56.10"):
        inflation = next(
            f
            for f in build_exposure(make_company(okved_code=okved, **NO_GROUP), []).factors
            if f.code == "inflation"
        )
        assert inflation.level == "high" and "по марже" in inflation.channel.text
    parts = next(
        f
        for f in build_exposure(make_company(okved_code="45.31", **NO_GROUP), []).factors
        if f.code == "inflation"
    )
    assert parts.level == "medium"
