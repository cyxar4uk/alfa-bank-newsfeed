from ingest.news.expectations import extract, sentences


def test_analysts_expect_key_rate_with_value_and_verbatim_quote():
    lead = (
        "Банк России в пятницу примет решение по ставке. Опрошенные аналитики ожидают сохранения "
        "ключевой ставки на уровне 14%. Рубль торгуется стабильно."
    )
    found = extract("ЦБ проведёт заседание по ставке", lead)
    assert len(found) == 1
    e = found[0]
    assert e.who_kind == "analysts"
    assert e.indicator == "rate"
    assert e.values == ["14%"]
    assert e.quote in lead


def test_government_forecast_and_international_org():
    found = extract(
        "Минэкономразвития ухудшило прогноз инфляции на 2026 год до 7,5%",
        "МВФ снизил прогноз роста ВВП Франции с 0,9% до 0,4%.",
    )
    kinds = {e.who_kind for e in found}
    assert "government" in kinds
    gov = next(e for e in found if e.who_kind == "government")
    assert gov.indicator == "inflation" and "7,5%" in gov.values


def test_market_expectations_for_currency():
    found = extract(
        "Участники рынка ждут ослабления рубля", "Трейдеры закладывают курс 90 руб. за доллар к концу года."
    )
    assert any(e.who_kind == "market" and e.indicator == "fx" for e in found)


def test_inflation_expectations_metric_is_not_someones_forecast():
    assert extract("Инфляционные ожидания населения в августе снизились", "") == []


def test_unattributed_vague_statements_are_skipped():
    # нет показателя из каталога — сравнивать с банком нечего
    assert extract("ЦСКА рассчитывает на 35 миллионов евро за полузащитника", "") == []
    assert extract("Бронирования идут стабильно, прогнозировать спрос сложно", "") == []


def test_no_marker_no_expectation():
    assert extract("Банк России сохранил ключевую ставку 14%", "Решение принято единогласно.") == []


def test_sentences_split_keeps_numbers_together():
    parts = sentences("Ставка 14,0%. Инфляция 6,1% г/г. «Кавычки» тоже.")
    assert parts == ["Ставка 14,0%.", "Инфляция 6,1% г/г.", "«Кавычки» тоже."]


def test_indicator_from_previous_sentence_and_dollar_values():
    found = extract("Нефть дорожает", "Цена Brent превысила $112. Аналитики ожидают роста до $120.")
    assert len(found) == 1
    assert found[0].indicator == "commodity_oil_gas" and found[0].values == ["$120"]


def test_lead_repeating_title_gives_one_expectation():
    title = "Аналитики ожидают сохранения ключевой ставки на уровне 14%"
    found = extract(title, title + ". Решение объявят в пятницу.")
    assert len(found) == 1


def test_company_name_in_quotes_and_mayor_is_not_ministry():
    found = extract("Компания «Северсталь» прогнозирует снижение цен на сталь", "")
    assert found[0].who == "Северсталь" and found[0].who_kind == "company"
    mayor = extract("Мэр Москвы ожидает роста налоговых доходов бюджета", "")
    assert all(e.who_kind != "government" for e in mayor)


def test_truncated_lead_ellipsis_not_in_quote():
    found = extract("Рынок", "Аналитики ожидают роста ключевой ставки до 16% к концу…")
    assert found[0].quote.endswith("к концу")


def test_gdp_forecast_is_not_attributed_to_neighbour_factor():
    lead = "Потребительский спрос во Франции слабеет. МВФ снизил прогноз роста ее ВВП на 2026 год с 0,9% до 0,4%."
    assert extract("Франция притормаживает", lead) == []
