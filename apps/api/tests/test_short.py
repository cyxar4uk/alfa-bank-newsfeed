from api.contract import ChainChannel
from api.short import SHORT_MAX, chain_short, factor_short


def test_factor_short_keeps_number_and_drops_codes_and_marks():
    rate = factor_short(
        "rate", "Стоимость заёмных денег", "собственный кредит в банке; также кредиты у 11 компаний группы"
    )
    assert rate == "Стоимость долга: собственный кредит в банке, кредиты у 11 компаний группы"
    group = factor_short(
        "gov",
        "Госрасходы и бюджет",
        "компании группы в стройке (41.20, 42.11) — 51 % выручки группы; также гарантии",
    )
    assert group == "Госзаказ и бюджет: компании группы в стройке — 51 % выручки группы"
    # не код: десятичное число остаётся
    assert factor_short("rate", "Ставка", "ставка 16.5 % годовых") == "Стоимость долга: ставка 16.5 % годовых"
    assert factor_short("fx", "Курс", "ВЭД (оценка по отрасли): 44 % платежей; направление — экспорт") == (
        "Курс: ВЭД: 44 % платежей"
    )


def test_no_honest_short_line_is_none():
    # без числа из данных
    assert (
        factor_short("fx", "Курс валют", "ВЭД: ОАЭ, Алжир, Индия; направление — экспорт (оценка по отрасли)")
        is None
    )
    own = "своя отрасль — нефть, газ и топливо: 46.71 Торговля оптовая твердым топливом"
    assert factor_short("commodity_oil", "Сырьё", own) is None
    # не помещается целиком
    assert factor_short("gov", "Госрасходы", "у 3 " + "очень длинное описание " * 10) is None


def test_factor_short_fits_limit_by_dropping_lists():
    long = factor_short(
        "fx",
        "Курс валют",
        "через поставщиков своей группы с ВЭД: 44 % всех платежей идут 3 компаниям группы"
        " (Индия, Камбоджа, Китай, ОАЭ, Турция); что они импортируют — оценка по отрасли",
    )
    assert long == "Курс: через поставщиков своей группы с ВЭД: 44 % всех платежей идут 3 компаниям группы"
    assert len(long) <= SHORT_MAX


def test_chain_short():
    def channel(kind, share):
        return ChainChannel(
            kind=kind,
            okved="56",
            sector="общепит",
            share=share,
            weight=1,
            strength=share,
            text="",
            counterparties=0,
        )

    assert chain_short(channel("buyers", 0.531)) == "Через покупателей: общепит — 53 % поступлений"
    assert chain_short(channel("suppliers", 0.32)) == "Через поставщиков: общепит — 32 % платежей"
    assert chain_short(channel("group", 0.2)) == "Через компании группы: общепит — 20 % выручки группы"
    assert chain_short(channel("direct", 1.0)) is None  # своя отрасль: числа нет
