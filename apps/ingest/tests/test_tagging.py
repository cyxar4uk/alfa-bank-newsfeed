import json
import re

import pytest

from ingest.models import FactorLink, SectorLink, Source, Tags
from ingest.news.expectations import extract
from ingest.tagging.llm import ApiLlmTagger, MockLlmTagger, make_llm_tagger, merge_tags, parse_answer
from ingest.tagging.rules import blank, load_dictionaries, strength_of, tag

CATALOG_B = {
    "rate",
    "deposit_yield",
    "fx",
    "ved_logistics",
    "consumer",
    "labor",
    "gov",
    "commodity_metals",
    "commodity_oil_gas",
    "commodity_gold",
    "commodity_fertilizers",
    "commodity_agro",
    "inflation",
}


def factor(tags: Tags, code: str) -> FactorLink | None:
    return next((f for f in tags.factors if f.code == code), None)


def sector(tags: Tags, okved: str) -> SectorLink | None:
    return next((s for s in tags.sector_links if s.okved == okved), None)


def test_dictionary_covers_factor_catalog_b():
    codes = {e.code for e in load_dictionaries().factors}
    assert CATALOG_B <= codes
    # сверх каталога — только налоги и регулирование, нужные роли главбуха
    assert codes - CATALOG_B == {"tax_regulation"}


def test_strength_depends_on_place_and_pattern():
    assert strength_of([("title", "strong", "ключевую ставку")]) == 1.0
    assert strength_of([("title", "weak", "кредит")]) == 0.6
    assert strength_of([("lead", "strong", "ключевую ставку")]) == 0.6
    assert strength_of([("lead", "weak", "кредит")]) == 0.3
    assert strength_of([("lead", "weak", "кредит"), ("lead", "weak", "займы")]) == 0.4
    assert strength_of([]) == 0.0


def test_key_rate_in_title_is_strong_with_evidence():
    tags = tag("Банк России сохранил ключевую ставку на уровне 14% годовых", "Совет директоров принял решение.")
    rate = factor(tags, "rate")
    assert rate.strength == 1.0
    assert any("в заголовке" in e for e in rate.evidence)
    assert tags.event_type == "решение регулятора"
    assert "Россия" in tags.countries
    assert tags.topics[0] == rate.name


def test_factor_only_in_lead_is_weaker():
    tags = tag("Итоги недели на рынках", "Инфляция в сентябре замедлилась до 6,1%.")
    assert factor(tags, "inflation").strength == 0.6


def test_commodity_factor_implies_producing_sectors():
    tags = tag("Цена нефти Brent превысила $112 за баррель", "")
    assert factor(tags, "commodity_oil_gas").strength == 1.0
    link = sector(tags, "06")
    assert link.strength == 1.0 and link.via in ("text", "factor:commodity_oil_gas")
    assert sector(tags, "19") is not None
    assert {"06", "19"} <= set(tags.okved)


def test_sector_named_in_text_beats_implied():
    tags = tag("Северсталь и НЛМК ожидают роста цен на сталь", "")
    link = sector(tags, "24")
    assert link.via == "text" and link.strength == 1.0
    assert all(len(code) == 2 for code in tags.okved)


def test_airport_news_hits_airport_and_airlines_not_post():
    tags = tag("В аэропорту Казани ввели временные ограничения", "")
    assert sector(tags, "52").strength == 1.0
    assert sector(tags, "51") is not None
    assert sector(tags, "53") is None
    assert factor(tags, "region").strength == 1.0
    assert "Республика Татарстан" in tags.regions


def test_word_forms_are_matched():
    tags = tag("Инфляционные ожидания предприятий выросли", "Ипотечные кредиты дорожают, зарплаты растут.")
    assert factor(tags, "inflation") is not None
    assert factor(tags, "rate") is not None
    assert factor(tags, "labor") is not None
    assert sector(tags, "68") is not None


def test_regions_by_city_and_countries_by_adjective():
    tags = tag("Екатеринбургский завод начал экспорт труб в Китай и Казахстан", "Китайские покупатели довольны.")
    assert "Свердловская область" in tags.regions
    assert {"Китай", "Казахстан"} <= set(tags.countries)
    assert factor(tags, "ved_logistics") is not None


@pytest.mark.parametrize(
    "title, factor_code, okved",
    [
        ("Газета пишет о росте продаж", "commodity_oil_gas", None),  # газета — не газ
        ("Газпромбанк возобновил финансирование застройщика", "commodity_oil_gas", None),
        ("Getty Images начал процедуру банкротства", None, "64"),  # банкротство — не банк
        ("Розничные инвесторы продолжили покупать облигации", "consumer", "47"),
        ("Банк России провёл Евразийский круглый стол", "commodity_metals", "24"),  # не ЕВРАЗ
        ("МВФ снизил прогноз роста ВВП Франции", "fx", None),  # Международный валютный фонд — не валюта
    ],
)
def test_known_false_friends_are_not_tagged(title, factor_code, okved):
    tags = tag(title, "")
    if factor_code:
        assert factor(tags, factor_code) is None
    if okved:
        assert sector(tags, okved) is None


def test_gazprombank_is_a_bank():
    assert sector(tag("Газпромбанк возобновил финансирование застройщика", ""), "64") is not None


def test_moscow_exchange_is_not_moscow_region():
    tags = tag("Индекс Московской биржи вырос на 2%", "")
    assert "Москва" not in tags.regions
    assert sector(tags, "66") is not None


def test_empty_text_gives_empty_tags():
    tags = tag("", "")
    assert tags.factors == [] and tags.sector_links == [] and tags.event_type is None


def test_every_sector_has_two_digit_okved_and_unique_codes():
    d = load_dictionaries()
    codes = [code for e in d.sectors for code in e.okved]
    assert all(len(c) == 2 and c.isdigit() for c in codes)
    assert len(codes) == len(set(codes))
    implied = {code for e in d.factors for code, _ in e.implies}
    assert implied <= set(codes)


def test_llm_mock_keeps_rule_tags_and_marks_step():
    src = Source(id="s", kind="news", title="t", publisher="p", fragment="f")
    base = tag("ЦБ сохранил ключевую ставку", "")
    merged = merge_tags(base, MockLlmTagger().tag(src))
    assert [f.code for f in merged.factors] == [f.code for f in base.factors]
    assert merged.tagged_by == ["rules", "llm-mock"]


def test_merge_tags_adds_new_and_keeps_stronger():
    base = Tags(
        factors=[FactorLink(code="rate", name="ставка", strength=0.3, evidence=["«кредит» в тексте"])],
        sector_links=[SectorLink(okved="24", name="металлургия", strength=1.0, via="text")],
        tagged_by=["rules"],
    )
    extra = Tags(
        factors=[
            FactorLink(code="rate", name="ставка", strength=0.6, evidence=["«ставка» (модель)"]),
            FactorLink(code="fx", name="курс", strength=0.3),
        ],
        sector_links=[SectorLink(okved="24", name="металлургия", strength=0.6, via="llm")],
        event_type="статистика",
        tagged_by=["llm:x"],
    )
    merged = merge_tags(base, extra)
    rate = next(f for f in merged.factors if f.code == "rate")
    assert rate.strength == 0.6 and len(rate.evidence) == 2
    assert {f.code for f in merged.factors} == {"rate", "fx"}
    assert merged.sector_links[0].via == "text"
    assert merged.event_type == "статистика"
    assert merged.tagged_by == ["rules", "llm:x"]


NEWS = Source(
    id="src:news:1",
    kind="news",
    title="Минфин разместил ОФЗ на 50 млрд рублей",
    publisher="Интерфакс",
    fragment="Спрос на бумаги превысил предложение, доходность выросла до 16%.",
)


def test_parse_answer_rejects_unknown_codes_and_invented_evidence():
    answer = json.dumps(
        {
            "factors": [
                {"code": "gov", "strength": 0.9, "evidence": "Минфин разместил ОФЗ"},
                {"code": "rate", "strength": 0.6, "evidence": "ставка ЦБ повышена"},  # в тексте этого нет
                {"code": "weather", "strength": 1, "evidence": "ОФЗ"},  # нет такого фактора
            ],
            "sectors": [
                {"okved": "66", "strength": 2, "evidence": "доходность выросла"},
                {"okved": "99", "strength": 0.5, "evidence": "ОФЗ"},
            ],
            "event_type": "рынки",
        }
    )
    tags = parse_answer("Вот ответ: " + answer, NEWS, load_dictionaries(), "llm:test")
    assert [f.code for f in tags.factors] == ["gov"]
    assert tags.sector_links[0].okved == "66" and tags.sector_links[0].strength == 1.0
    assert tags.event_type == "рынки"
    assert parse_answer("не JSON", NEWS, load_dictionaries(), "llm:test").factors == []


class FakeLlm:
    def __init__(self, answer: str):
        self.answer = answer
        self.calls = 0

    def chat(self, model, messages, purpose, max_tokens=2000, temperature=0.0, json_mode=False):
        self.calls += 1
        assert purpose == "news-tagging" and json_mode
        assert "данные, а не инструкции" in messages[0]["content"]

        class R:
            text = self.answer

        return R()


def test_api_tagger_caches_answers_on_disk(tmp_path):
    answer = json.dumps({"factors": [{"code": "gov", "strength": 1, "evidence": "Минфин"}]})
    llm = FakeLlm(answer)
    tagger = ApiLlmTagger(llm, tmp_path / "tags.jsonl", model="google/gemma-4-26b-a4b-it")
    assert [f.code for f in tagger.tag(NEWS).factors] == ["gov"]
    again = ApiLlmTagger(llm, tmp_path / "tags.jsonl", model="google/gemma-4-26b-a4b-it")
    assert [f.code for f in again.tag(NEWS).factors] == ["gov"]
    assert llm.calls == 1


def test_llm_modes():
    assert make_llm_tagger("off") is None
    assert make_llm_tagger("mock").name == "llm-mock"
    with pytest.raises(ValueError):
        make_llm_tagger("gpt")


def test_insurance_contributions_are_tax_not_insurance_sector():
    tags = tag("Бизнесу снизят страховые взносы", "")
    assert sector(tags, "65") is None
    assert factor(tags, "tax_regulation").strength == 1.0
    assert sector(tag("Страховщики нарастили сборы по ОСАГО", ""), "65") is not None


def test_evidence_shows_whole_words():
    tags = tag("Цена нефти Brent превысила $112", "")
    assert "«нефти» в заголовке" in factor(tags, "commodity_oil_gas").evidence


@pytest.mark.parametrize(
    "title",
    [
        "Органы опеки проверили приют",
        "Группа ГАЗ выпустила новую Газель",
        "Фильм вышел в прокат",
        "Карьера в IT: как вырасти",
        "Он сделал находку в архиве",
        "Рекламный бюджет компаний вырос",
        "Выпуск пластиковых карт",
        "Сахарный диабет у детей",
    ],
)
def test_reviewer_false_friends_give_nothing(title):
    tags = tag(title, "")
    assert tags.factors == [] and tags.sector_links == [] and tags.regions == []


def test_qualified_matches_still_work():
    assert factor(tag("ОПЕК+ сохранил добычу", ""), "commodity_oil_gas").strength == 1.0
    assert sector(tag("Цены на плоский прокат выросли", ""), "24") is not None
    assert factor(tag("Дефицит федерального бюджета вырос", ""), "gov").strength == 1.0
    assert factor(tag("Потребление электроэнергии выросло", ""), "consumer") is None
    assert sector(tag("Альфа-Банк снизил ставки по кредитам", ""), "64") is not None
    assert tag("СПБ Биржа вошла в НАУФОР", "").regions == []


# ложные срабатывания с живых лент 22–23.10: (заголовок, лид, факторы и отрасли, которых быть не должно)
LIVE_FALSE_POSITIVES = [
    ("ЦСКА рассчитывает на 35 миллионов евро за Кисляка, пишут СМИ", "", {"fx"}),
    (
        "Три человека пострадали в результате атак ВСУ в Белгородской области",
        "В Борисовском округе на автодороге Стригуны - Новоалександровка в результате атаки дрона на легковой "
        "автомобиль пострадал мужчина.",
        {"29", "42"},
    ),
    (
        "В Италии остановлено производство моцареллы из-за забастовки дальнобойщиков",
        "Это произошло из-за блокады автодорог бастующими дальнобойщиками.",
        {"42"},
    ),
    ('Газманов заявил, что потерял неопубликованные песни из-за сбоев "Яндекса"', "", {"commodity_oil_gas", "06"}),
    ("Львова-Белова навестила мать и детей, пострадавших при взрыве газа", "", {"commodity_oil_gas", "06", "19"}),
    (
        "СМИ: мадридский «Реал» вернется на церемонию «Золотой мяч» после двух лет бойкота",
        "Мадридский «Реал» будет широко представлен на церемонии вручения «Золотого мяча».",
        {"commodity_gold", "07"},
    ),
    (
        "Силуанов о бюджете: нужно жить экономнее, но без затягивания поясов",
        "Один из депутатов спросил его, говоря о бюджете страны.",
        {"consumer"},
    ),
    (
        "Суд в Москве отклонил жалобу Euroclear на взыскание €200 млрд по иску ЦБ",
        "Суды постановили взыскать с депозитария €200 млрд.",
        {"deposit_yield", "fx"},
    ),
    ("Банк России допустил первые цифровые депозитарии и криптообменники к работе", "", {"deposit_yield"}),
    (
        "Дилеры раскинули сети // Количество шоурумов автомобильных брендов достигло рекорда",
        "Подобная ситуация складывалась в 2023 году.",
        {"52"},
    ),
    ("Цифровой рубль: старт использования", "", {"fx"}),
    ("ЦБ протестирует офлайн-платежи цифровыми рублями в 2027 году", "", {"fx"}),
    ("Цена нефти марки Brent поднялась выше 116 долларов за баррель", "", {"fx"}),
    ("Биржевая цена на золото опустилась ниже четырех тысяч долларов за унцию", "", {"fx"}),
    ("Vonovia может потерять более 8 млрд евро в случае национализации квартир в Берлине", "", {"fx"}),
    (
        "«Коммерсантъ» узнал о предложении Минэнерго повысить цены на топливо на АЗС",
        "Бензин и дизтопливо на АЗС могут подорожать на 2,1 рубля за литр.",
        {"fx"},
    ),
    (
        'В Петербурге задержаны "черные риелторы", подозреваемые в отравлении жертв метанолом',
        "Задержаны шесть человек, которых обвиняют в убийствах и мошенничестве с недвижимостью.",
        {"68"},
    ),
    ("Суд в Москве арестовал экс-депутата Госдумы Михайлова", "", {"tax_regulation"}),
    ("В Госдуме объяснили, как проблемы с PHP могут повлиять на российские сайты", "", {"tax_regulation"}),
    (
        "ЦБ сохранил ключевую ставку на уровне 14%",
        "Банк России решил сохранить ключевую ставку, сообщает пресс-служба регулятора.",
        {"tax_regulation"},
    ),
    (
        "США за 100 дней блокады Ирана предотвратили экспорт его нефти на сумму $25 млрд",
        'Силы США возобновили морскую блокаду Ирана - своего рода "стальную стену".',
        {"commodity_metals", "24"},
    ),
    (
        "Монета, посвященная судебной системе России (01.10.2026)",
        "Банк России выпускает в обращение памятную серебряную монету номиналом 3 рубля. Серебряная монета "
        "номиналом 3 рубля (масса драгоценного металла в чистоте – 31,1 г) имеет форму круга.",
        {"commodity_gold", "commodity_metals", "fx", "07", "24"},
    ),
    ("Минфин США исключил Венесуэлу из списка вызывающих озабоченность стран", "", {"gov"}),
    (
        "Мосгорсуд оставил в СИЗО пострадавшего при задержании политолога",
        "Защита опасается, что без должной медицинской помощи политолог может остаться инвалидом.",
        {"86"},
    ),
    # те же ошибки, которых в снимке нет, но в лентах они обычны
    ("Израиль нанес удары по сектору Газа", "", {"commodity_oil_gas", "06"}),
    ("Российская фигуристка завоевала золото чемпионата Европы", "", {"commodity_gold", "07"}),
    ("Пострадавшего в ДТП доставили в больницу", "Ему оказали медицинскую помощь.", {"86"}),
    ("Пострадавших увезли в больницу", "", {"86"}),
    ("Израиль нанес удар по Газе", "", {"commodity_oil_gas", "06"}),
    ("Утечка газа в жилом доме", "", {"commodity_oil_gas"}),
    ("Взрыв газовоздушной смеси в подъезде", "", {"commodity_oil_gas"}),
    ("Жильцы отравились угарным газом", "", {"commodity_oil_gas"}),
    ("Полиция применила слезоточивый газ", "", {"commodity_oil_gas"}),
    ("Газовый баллон взорвался на даче", "", {"commodity_oil_gas"}),
    ("Газон в парке обновили", "", {"commodity_oil_gas"}),
    ("Продажи газированных напитков выросли", "", {"commodity_oil_gas"}),
    ("ЦБ выпустит памятную монету из золота", "", {"commodity_gold", "07"}),
    ("Российский пловец стал золотым призером чемпионата мира", "", {"commodity_gold", "07"}),
    ("Минфин Казахстана сократил расходы", "", {"gov"}),
    ("Цифровой юань расширил зону расчетов", "", {"fx"}),
    ("Спрос на депозитарные расписки вырос", "", {"deposit_yield"}),
    ("Ремонт дорогостоящего оборудования подорожал", "", {"42"}),
]


@pytest.mark.parametrize("title, lead, forbidden", LIVE_FALSE_POSITIVES)
def test_live_false_positives_are_not_tagged(title, lead, forbidden):
    tags = tag(title, lead)
    found = {f.code for f in tags.factors} | {s.okved for s in tags.sector_links}
    assert not found & forbidden


@pytest.mark.parametrize(
    "title, lead, code, strength",
    [
        ("Курс евро превысил 95 рублей", "", "fx", 1.0),
        ("ЦБ впервые с августа опустил курс доллара ниже 82 рублей", "", "fx", 1.0),
        ("Аналитик объяснил, почему рубль продолжит укрепляться", "", "fx", 0.6),
        ("Доллар подешевел до 80 рублей", "", "fx", 0.6),
        ("Продажи автомобилей в России выросли на 12%", "", "45", 1.0),
        ("Продажи автомобилей в России выросли на 12%", "", "consumer", 0.6),
        ("Алиханов: выпуск легковых авто в России вырос более чем на 27%", "", "29", 1.0),
        ("АвтоВАЗ сократит производство", "", "29", 1.0),
        ("Строительство автодороги М-12 до Тюмени ускорят", "", "42", 1.0),
        ("Автодор отложил ремонт трассы", "", "42", 1.0),
        ("Газпром нарастил добычу газа", "", "commodity_oil_gas", 1.0),
        ("Цена золота обновила рекорд", "", "commodity_gold", 1.0),
        ("Спрос на жильё упал", "", "consumer", 0.6),
        ("Ставки по депозитам снизились", "", "deposit_yield", 1.0),
        ("Минфин разместил ОФЗ на 50 млрд рублей", "", "gov", 0.6),
        ("Госдума приняла законопроект о налоге на сверхприбыль", "", "tax_regulation", 1.0),
        ("Больницы региона получат новое оборудование", "", "86", 1.0),
        ("Дефицит медицинской помощи в регионах растёт", "", "86", 1.0),
        ("Атаки на склады Wildberries замедлили продажи", "", "52", 1.0),
        # единица и год перед валютой — не сумма
        ("Стоимость 1 евро на Мосбирже впервые с марта превысила 100 рублей", "", "fx", 0.6),
        ("К концу 2026 юань будет стоить 13 рублей", "", "fx", 0.6),
        ("Итоги торгов", "Индекс закрылся на отметке 2900. Доллар при этом подешевел до 80 рублей.", "fx", 0.3),
        ("Рекордная цена принесла золотодобытчикам сверхприбыль", "", "commodity_gold", 1.0),
        ("Больше всего от кризиса выиграли золото и биткоин", "", "commodity_gold", 1.0),
        ("Минздрав утвердил новые стандарты оказания медицинской помощи", "", "86", 1.0),
        ("Миллион россиян получили высокотехнологичную медицинскую помощь по ОМС", "", "86", 1.0),
        ("Новое оборудование поступило в больницы Татарстана", "", "86", 1.0),
        ("Российские производители легковых автомобилей сократили выпуск", "", "29", 1.0),
        ("Импорт легковых автомобилей из Китая упал вдвое", "", "29", 1.0),
        ("Облигации Автодора разместили на бирже", "", "42", 1.0),
        ("Тарифы на бытовой газ для населения вырастут", "", "commodity_oil_gas", 1.0),
        ("Газонефтяной конденсат подорожал", "", "commodity_oil_gas", 1.0),
    ],
)
def test_real_links_survive_noise_filters(title, lead, code, strength):
    tags = tag(title, lead)
    links = {f.code: f.strength for f in tags.factors} | {s.okved: s.strength for s in tags.sector_links}
    assert links.get(code) == strength


def test_noise_is_cut_only_from_factors_and_sectors():
    tags = tag("Минфин США продлил лицензию на переговоры о продаже активов ЛУКОЙЛа", "")
    assert factor(tags, "gov") is None
    assert "США" in tags.countries
    assert factor(tags, "commodity_oil_gas").strength == 1.0
    # сумма в евро не делает новость событием курса, но остальная разметка на месте
    tags = tag("Сделка на 2 млрд евро: «Северсталь» купила завод", "")
    assert factor(tags, "fx") is None
    assert sector(tags, "24").strength == 1.0
    assert tags.event_type == "корпоративное событие"


def test_blank_keeps_length_and_erases_whole_words():
    pattern = re.compile("цифров\\w* рубл")
    text = "счета цифрового рубля открыты"
    out = blank(pattern, text)
    assert len(out) == len(text)
    assert out.split() == ["счета", "открыты"]
    assert blank(None, text) == text


def test_expectations_ignore_currency_amounts():
    found = extract("Аналитики ожидают, что сделка составит 35 млн евро", "")
    assert all(e.indicator != "fx" for e in found)
    found = extract("Аналитики ожидают, что к концу года доллар будет стоить 110 рублей", "")
    assert [e.indicator for e in found] == ["fx"]


class BrokenLlm:
    def __init__(self):
        self.calls = 0

    def chat(self, *args, **kwargs):
        from ingest.llm import LlmUnavailable

        self.calls += 1
        raise LlmUnavailable("модель ответила 402: Budget has been exceeded")


def test_api_tagger_stops_calling_after_first_failure(tmp_path):
    llm = BrokenLlm()
    tagger = ApiLlmTagger(llm, tmp_path / "tags.jsonl")
    for i in range(5):
        assert tagger.tag(NEWS.model_copy(update={"id": f"src:news:{i}"})) == Tags()
    assert llm.calls == 1 and tagger.failures == 5


def test_gateway_200_without_choices_is_llm_unavailable(monkeypatch):
    import httpx

    from ingest.llm import LlmClient, LlmUnavailable

    class Resp:
        status_code = 200
        text = '{"error": {"message": "budget exceeded"}}'

        def json(self):
            return {"error": {"message": "budget exceeded"}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    client = LlmClient("секрет", "https://example.invalid/v1")
    with pytest.raises(LlmUnavailable) as err:
        client.chat("m", [], purpose="test")
    assert "секрет" not in str(err.value)
