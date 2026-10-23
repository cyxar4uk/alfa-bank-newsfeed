from ingest.models import Source, Tags
from ingest.tagging.llm import MockLlmTagger, make_llm_tagger, merge_tags
from ingest.tagging.rules import load_dictionaries, tag_text


def test_key_rate_decision():
    tags = tag_text("Банк России сохранил ключевую ставку на уровне 14% годовых")
    assert "ключевая ставка" in tags.topics
    assert tags.event_type == "решение регулятора"
    assert "Россия" in tags.countries
    assert tags.tagged_by == ["rules"]


def test_sector_gives_two_digit_okved():
    tags = tag_text("Северсталь и НЛМК ожидают роста цен на сталь и прокат")
    assert "металлургия" in tags.sectors
    assert {"24", "07"} <= set(tags.okved)
    assert all(len(code) == 2 for code in tags.okved)
    assert "металлы" in tags.topics


def test_word_forms_are_matched():
    tags = tag_text("Инфляционные ожидания предприятий выросли; ипотечные кредиты дорожают")
    assert "инфляция" in tags.topics
    assert "стройка и недвижимость" in tags.topics
    assert "кредитование" in tags.topics


def test_regions_by_city_and_countries_by_adjective():
    tags = tag_text("Екатеринбургский завод начал экспорт труб в Китай и Казахстан, китайские покупатели довольны")
    assert "Свердловская область" in tags.regions
    assert {"Китай", "Казахстан"} <= set(tags.countries)
    assert "санкции и ВЭД" in tags.topics


def test_known_false_friends_are_not_tagged():
    # «газета» — не газ, «Газпромбанк» — банк, а не газ; «почти» — не почта; «стали» — глагол, не металл
    tags = tag_text("Газета пишет: Газпромбанк возобновил финансирование, почти все клиенты стали довольны")
    assert "нефть и газ" not in tags.topics
    assert "нефть и газ" not in tags.sectors
    assert "транспорт и логистика" not in tags.sectors
    assert "металлы" not in tags.topics
    assert "финансы и банки" in tags.sectors


def test_retail_investors_are_not_retail_trade():
    tags = tag_text("Розничные инвесторы продолжили покупать облигации")
    assert "ритейл и потребление" not in tags.topics
    assert "долговой рынок" in tags.topics


def test_moscow_exchange_is_not_moscow_region():
    tags = tag_text("Индекс Московской биржи вырос на 2%")
    assert "Москва" not in tags.regions
    assert "фондовый рынок" in tags.topics


def test_empty_text_gives_empty_tags():
    tags = tag_text("")
    assert tags.topics == [] and tags.sectors == [] and tags.event_type is None


def test_every_dictionary_entry_compiles_and_sectors_have_okved():
    d = load_dictionaries()
    assert len(d.topics) >= 12
    assert all(e.okved for e in d.sectors)
    assert len({e.name for e in d.regions}) == len(d.regions)


def test_llm_mock_keeps_rule_tags_and_marks_step():
    src = Source(id="s", kind="news", title="t", publisher="p", fragment="f")
    base = tag_text("ЦБ сохранил ключевую ставку")
    merged = merge_tags(base, MockLlmTagger().tag(src))
    assert merged.topics == base.topics
    assert merged.tagged_by == ["rules", "llm-mock"]


def test_merge_tags_unions_lists_and_fills_missing_event_type():
    base = Tags(topics=["инфляция"], okved=["24"], tagged_by=["rules"])
    extra = Tags(topics=["инфляция", "валюта"], okved=["07"], event_type="статистика", tagged_by=["llm"])
    merged = merge_tags(base, extra)
    assert merged.topics == ["инфляция", "валюта"]
    assert merged.okved == ["07", "24"]
    assert merged.event_type == "статистика"


def test_llm_modes():
    assert make_llm_tagger("off") is None
    assert make_llm_tagger("mock").name == "llm-mock"
