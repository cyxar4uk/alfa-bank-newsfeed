"""Необязательное извлечение модели: цитаты проверены, истинность интерпретации не подтверждена.

Контракт v1: Tags.structured_event; отсутствие поля/None поддерживает старые материалы.
parse_event принимает только данные из того же запроса разметки, без дополнительных вызовов.
Невалидный объект отбрасывается целиком и не влияет на обычную разметку.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class QuotedValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=4, max_length=2000)


class EventStatus(QuotedValue):
    value: Literal["adopted", "proposed", "forecast", "opinion"]


class EventDirection(QuotedValue):
    value: Literal["increase", "decrease", "unchanged", "mixed", "unknown"]
    negated: bool = False
    time_constraint: str | None = Field(default=None, max_length=300)


class EventNumber(QuotedValue):
    # Без преобразования масштаба или единиц: «2,5», «млрд рублей», «п.п.».
    unit: str = Field(min_length=1, max_length=80)
    period: str | None = Field(default=None, max_length=300)


class StructuredEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    extraction_method: Literal["llm"] = "llm"
    validation: Literal["exact_quotes_only"] = "exact_quotes_only"
    status: EventStatus
    direction: EventDirection | None = None
    objects: list[QuotedValue] = Field(default_factory=list, max_length=12)
    geography: list[QuotedValue] = Field(default_factory=list, max_length=12)
    dates: list[QuotedValue] = Field(default_factory=list, max_length=12)
    numbers: list[EventNumber] = Field(default_factory=list, max_length=20)


_PROPOSAL = r"предлага\w*|предлож\w*|законопроект\w*|проект\w*|инициатив\w*"
_FORECAST = r"прогноз\w*|ожида\w*|может|могут|не\s+раньше|не\s+ранее"
_OPINION = r"по\s+мнению|счита\w*|полага\w*"
_ADOPTED = r"принял\w*|принят\w*|решил\w*|утверд\w*|вступ\w*\s+в\s+силу|ввел\w*|ввёл\w*"
_DOWN = r"сниж\w*|сниз\w*|сократ\w*|упал\w*|упасть|падени\w*|подешев\w*"
_UP = r"повыш\w*|повыс\w*|вырос\w*|рост\w*|увелич\w*|подорож\w*"
_SAME = r"сохран\w*|неизмен\w*|без\s+изменений"


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(rf"(?<!\w)(?:{pattern})(?!\w)", text, re.IGNORECASE))


def _contains(value: str, quote: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(value)}(?!\w)", quote))


def parse_event(data: object, title: str, fragment: str) -> StructuredEvent | None:
    """Строгая проверка формы, дословности и явных противоречий; не проверка факта.

    Статус и направление требуют контекст целого предложения: нельзя отрезать
    «предложил» или «не раньше» и тем самым изменить смысл цитаты.
    """
    try:
        event = StructuredEvent.model_validate(data)
    except (ValidationError, TypeError, ValueError):
        return None
    fields = (title, fragment)
    sentences = [s.strip() for text in fields for s in re.split(r"(?<=[.!?])\s+(?=[А-ЯA-Z])|\n+", text)]

    def exact(quote: str) -> bool:
        return any(_contains(quote, text) for text in fields)

    claims = [event.status, *event.objects, *event.geography, *event.dates, *event.numbers]
    if event.direction:
        claims.append(event.direction)
    if any(not exact(item.quote) for item in claims):
        return None
    if event.status.quote not in sentences:
        return None
    status, quote = event.status.value, event.status.quote
    if status == "adopted" and (
        _has(f"{_PROPOSAL}|{_FORECAST}|{_OPINION}", quote)
        or not _has(_ADOPTED, quote)
        or _has(r"не\s+(?:принял\w*|принят\w*|утверд\w*|решил\w*)", quote)
    ):
        return None
    markers = {"proposed": _PROPOSAL, "forecast": _FORECAST, "opinion": _OPINION}
    if status in markers and not _has(markers[status], quote):
        return None
    for item in [*event.objects, *event.geography, *event.dates]:
        if not _contains(item.value, item.quote):
            return None
    for number in event.numbers:
        if not re.fullmatch(r"[+−-]?\d+(?:[ .,\u00a0]\d+)*", number.value):
            return None
        # Число и единица должны стоять вместе, а не в разных частях предложения.
        if not re.search(
            rf"(?<![\w.,]){re.escape(number.value)}\s*{re.escape(number.unit)}(?!\w)", number.quote
        ):
            return None
        if number.period is not None and not _contains(number.period, number.quote):
            return None
    direction = event.direction
    if direction:
        if direction.quote not in sentences:
            return None
        quote = direction.quote
        temporal = re.search(r"не\s+(?:раньше|ранее)[^,;.!?]*", quote, re.IGNORECASE)
        if temporal and (not direction.time_constraint or temporal.group() not in direction.time_constraint):
            return None
        if direction.time_constraint is not None and not _contains(direction.time_constraint, quote):
            return None
        cue = {"increase": _UP, "decrease": _DOWN, "unchanged": _SAME}.get(direction.value)
        if cue and not _has(cue, quote):
            return None
        # Лексическое отрицание проверяется только как защитный фильтр, не как извлечение.
        negation = _has(rf"не\s+(?:будет|будут)\s+(?:{_UP}|{_DOWN})|не\s+(?:{_UP}|{_DOWN})", quote)
        if direction.value in ("increase", "decrease") and direction.negated != negation:
            return None
    return event
