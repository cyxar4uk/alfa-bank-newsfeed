import json

from ingest.models import Source, Tags
from ingest.news.pipeline import tag_source
from ingest.structured_event import parse_event
from ingest.tagging.llm import merge_tags, parse_answer
from ingest.tagging.rules import load_dictionaries


def event(status: str, quote: str, *, direction=None, numbers=None):
    return {
        "schema_version": 1,
        "extraction_method": "llm",
        "validation": "exact_quotes_only",
        "status": {"value": status, "quote": quote},
        "direction": direction,
        "objects": [{"value": "пошлину", "quote": quote}] if "пошлин" in quote else [],
        "geography": [],
        "dates": [],
        "numbers": numbers or [],
    }


def test_proposed_duty_is_not_accepted():
    quote = "Минфин предложил повысить пошлину на импорт стали."
    parsed = parse_event(event("proposed", quote), quote, "")
    assert parsed and parsed.status.value == "proposed"
    assert parse_event(event("adopted", quote), quote, "") is None


def test_adopted_duty_and_proposal_wording_are_distinguished():
    quote = "Правительство приняло пошлину на импорт стали."
    assert parse_event(event("adopted", quote), quote, "") is not None
    assert parse_event(event("proposed", quote), quote, "") is None


def test_direction_preserves_negation_and_not_before_constraint():
    quote = "По прогнозу, пошлину не будут повышать до 1 января 2027 года."
    value = event(
        "forecast",
        quote,
        direction={
            "value": "increase",
            "negated": True,
            "time_constraint": "до 1 января 2027 года",
            "quote": quote,
        },
    )
    parsed = parse_event(value, quote, "")
    assert parsed and parsed.direction and parsed.direction.negated
    assert parsed.direction.time_constraint == "до 1 января 2027 года"
    value["direction"]["negated"] = False
    assert parse_event(value, quote, "") is None


def test_decrease_not_before_requires_explicit_time_constraint():
    quote = "По прогнозу, снижение ставки ожидается не раньше 1 января 2027 года."
    value = event(
        "forecast",
        quote,
        direction={"value": "decrease", "negated": False, "quote": quote},
    )
    assert parse_event(value, quote, "") is None
    value["direction"]["time_constraint"] = "не раньше 1 января 2027 года"
    parsed = parse_event(value, quote, "")
    assert parsed and parsed.direction and parsed.direction.value == "decrease"


def test_percent_and_percentage_points_keep_distinct_units():
    quote = "ЦБ принял решение: ставка выросла на 2% и инфляция — на 2 п.п. за год."
    numbers = [
        {"value": "2", "unit": "%", "period": None, "quote": "на 2%"},
        {"value": "2", "unit": "п.п.", "period": "за год", "quote": "на 2 п.п. за год"},
    ]
    parsed = parse_event(event("adopted", quote, numbers=numbers), quote, "")
    assert parsed is not None
    assert [number.unit for number in parsed.numbers] == ["%", "п.п."]
    numbers[0]["unit"] = "п.п."
    assert parse_event(event("adopted", quote, numbers=numbers), quote, "") is None


def test_metadata_flows_through_existing_llm_tagging_and_pipeline():
    quote = "Минфин предложил повысить пошлину на импорт стали на 2 п.п. с 1 января."
    structured = event(
        "proposed",
        quote,
        direction={"value": "increase", "negated": False, "quote": quote},
        numbers=[{"value": "2", "unit": "п.п.", "period": "с 1 января", "quote": quote}],
    )
    src = Source(id="s", kind="news", title=quote, publisher="Источник", fragment=quote)
    parsed = parse_answer(
        json.dumps({"structured_event": structured}, ensure_ascii=False),
        src,
        load_dictionaries(),
        "llm:test",
    )
    assert parsed.structured_event and parsed.structured_event.status.value == "proposed"
    merged = merge_tags(src.tags, parsed)
    assert merged.structured_event == parsed.structured_event
    tagged = tag_source(src, llm=type("Tagger", (), {"tag": lambda self, _: parsed})())
    assert tagged.tags.structured_event and tagged.tags.structured_event.numbers[0].unit == "п.п."


def test_json_integer_schema_version_and_string_fields_parse_strictly():
    quote = "Минфин предложил повысить пошлину на импорт стали."
    payload = json.dumps({"structured_event": event("proposed", quote)}, ensure_ascii=False)
    src = Source(id="s", kind="news", title=quote, publisher="Источник", fragment=quote)
    tags = parse_answer(payload, src, load_dictionaries(), "llm:test")
    assert tags.structured_event is not None
    assert tags.structured_event.schema_version == 1
    assert tags.structured_event.status.value == "proposed"


def test_tag_source_without_llm_leaves_optional_metadata_empty():
    quote = "Минфин предложил повысить пошлину на импорт стали."
    src = Source(id="s", kind="news", title=quote, publisher="Источник", fragment=quote)
    tagged = tag_source(src)
    assert tagged.tags.structured_event is None


def test_old_or_invalid_metadata_stays_optional():
    assert Tags.model_validate({}).structured_event is None
    src = Source(id="s", kind="news", title="Новость", publisher="Источник", fragment="Текст")
    parsed = parse_answer('{"structured_event":{"status":"adopted"}}', src, load_dictionaries(), "llm:test")
    assert parsed.structured_event is None
