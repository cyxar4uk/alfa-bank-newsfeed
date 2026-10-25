"""«К чему уязвима компания»: 5–7 факторов карты чувствительности в порядке, важном для роли.

Только то, что есть в карте (`api.exposure`): сила, почему (канал с числами из данных банка, без кодов),
оценка ли это по отрасли. К каждому — что с фактором на этой неделе (последняя новость, где он главная тема),
позиция банка по теме и число новостей по дням. Порядок — сила × вес роли из `roles.toml`. `limits` — честно,
чего не оцениваем: покрытие платежами и факторы без данных.
"""

import datetime as dt
import re
from collections.abc import Callable
from typing import Any

from api.bankview import bank_view
from api.consequence import direction_label
from api.contract import ExposureMap, FactorExposure, FeedItem, RiskFactor, RiskNow
from api.numbers import fmt_percent
from api.ranking import MSK, NewsEvent, RankingConfig
from api.short import _CODE, _EMPTY_PARENS, _SERVICE
from api.takeaway import WATCH
from api.week import TAG_MIN, story_key, topic_counts

FACTORS_MIN, FACTORS_MAX = 5, 7
STRENGTH = {"high": "strong", "medium": "notable", "low": "weak"}
COVERAGE_LOW = 0.1  # платежи покрывают меньше 10 % выручки — цепочки через контрагентов не оцениваем
LIMITS_MAX = 4


def why(factor: FactorExposure) -> str:
    """Почему компания уязвима: канал фактора человеческим языком — без кодов и служебных пометок."""
    text = factor.channel.text if factor.channel else factor.label
    text = _EMPTY_PARENS.sub("", _CODE.sub("", _SERVICE.sub("", text))).strip()
    text = text.replace("своя отрасль", "ваша отрасль").replace("; также ", "; ")
    # вид деятельности из справочника пишется с заглавной: «…топливо: Торговля оптовая…» → «…: торговля…»
    # (только начало фразы из нескольких слов — страны «Киргизия, Казахстан» остаются с заглавной)
    text = re.sub(r": ([А-ЯЁ])(?=[а-яё]+ [а-яё])", lambda m: ": " + m.group(1).lower(), text)
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")


def _when(item: FeedItem) -> dt.datetime:
    return item.source.published_at or dt.datetime.min.replace(tzinfo=MSK)


def latest(items: list[FeedItem], code: str) -> FeedItem | None:
    """Последняя новость недели о факторе: где он главная тема (`api.week.story_key`); таких нет — где у
    фактора сильная метка (от 0,5), а не побочное упоминание. Из заметных событий (оценка от 0,3 — те,
    что лента не сворачивает); заметных нет — из всех."""
    visible = [i for i in items if i.relevance.score >= WATCH] or items
    main = [i for i in visible if story_key(i) == code]
    strong = main or [
        i
        for i in visible
        if any(
            t.kind == "factor" and t.code == code and (t.event_strength or 0) >= TAG_MIN
            for t in i.relevance.breakdown
        )
    ]
    return max(strong, key=lambda i: (_when(i), i.relevance.score), default=None)


def now_for(items: list[FeedItem], code: str, exposure: ExposureMap) -> tuple[FeedItem, str] | None:
    """Что с фактором сейчас: последняя новость недели о нём и её направление («Дорожает», «Держится»;
    не определить — «Новое»)."""
    first = latest(items, code)
    if first is None:
        return None
    return first, direction_label(first, code, exposure)


def order(exposure: ExposureMap, role: str, config: RankingConfig) -> list[FactorExposure]:
    """Факторы с силой — по силе × весу роли; 5–7 штук (меньше, если у компании меньше факторов)."""
    role_cfg = config.roles.get(role) or config.roles["other"]
    known = [f for f in exposure.factors if f.strength and f.level in STRENGTH]
    ranked = sorted(known, key=lambda f: (-(f.strength or 0) * role_cfg.weight(f.code), f.code))
    return ranked[:FACTORS_MAX]


def limits(exposure: ExposureMap, revenue_coverage: float | None) -> list[str]:
    """Чего не оцениваем: покрытие платежами и факторы без данных — с числом."""
    result = []
    if revenue_coverage is not None and revenue_coverage < COVERAGE_LOW:
        result.append(
            "Не оцениваем спрос покупателей и поставщиков: платежи в выгрузке покрывают "
            f"{fmt_percent(revenue_coverage)} выручки, цепочки через контрагентов не строим."
        )
    missing = [f.label.lower() for f in exposure.factors if f.level == "no_data"]
    if missing:
        result.append(f"Нет данных, чтобы оценить: {', '.join(missing)}.")
    for warning in exposure.warnings:
        if result and "покрывают" in warning:
            continue  # то же покрытие платежами — уже сказано выше
        result.append(warning[:1].upper() + warning[1:] + ("" if warning.endswith(".") else "."))
    return result[:LIMITS_MAX]


def risk_factor(
    factor: FactorExposure,
    items: list[FeedItem],
    events: list[NewsEvent],
    days: list[dt.date],
    exposure: ExposureMap,
    aliases: dict[str, str],
    bank_fragments: Callable[[list[str], str], list[Any]] | None,
) -> RiskFactor:
    found = now_for(items, factor.code, exposure)
    now = None
    if found is not None:
        event, direction = found
        published = event.source.published_at
        now = RiskNow(
            event_id=event.event_id,
            title=event.event.title.split(" // ")[0],
            direction=direction,
            publisher=event.source.publisher,
            date=published.astimezone(MSK).date() if published else event.event.date,
        )
    bank = bank_view(factor.code, bank_fragments, now.title if now else None, now.date if now else None)
    counts = topic_counts(events, factor.code, days, aliases)
    return RiskFactor(
        code=factor.code,
        label=factor.label,
        strength=STRENGTH[factor.level],
        why=why(factor),
        is_estimate=factor.estimate,
        now=now,
        bank=bank,
        week_counts=counts,
        news_count=sum(counts),
    )
