"""«Главное за неделю»: 3–5 сюжетов недели — события одной темы за 7 дней, а не склейка дней.

Тема события — его главная причина в ленте: фактор (ставка, нефть, курс…) или своя отрасль и цепочка
(«industry:<ОКВЭД>»). Сюжет — все события недели с этой темой, задевающие компанию; главное — с наибольшей
оценкой. Динамика и пик — по числу новостей темы по дням: сколько новостей недели размечено этим фактором
(сила связи от 0,5) или этой отраслью, задевают они компанию или нет. Вывод сюжета — вывод главного события,
с охватом группы из общей функции (`api.coverage`).
"""

import datetime as dt
from collections.abc import Iterable

from api.consequence import consequence
from api.contract import ExposureMap, FeedItem, MainAction, Peak, Story
from api.ranking import MSK, NewsEvent
from api.takeaway import about, gist, main_reason

DAYS = 7
STORIES_MIN, STORIES_MAX = 3, 5
TAG_MIN = 0.5  # сила связи новости с темой, с которой она идёт в счётчик
DYNAMICS_GAP = 0.25  # на сколько среднее в день должно измениться, чтобы сюжет «усилился» или «утих»
# фон, а не сюжет: «события региона» — происшествия, их метку ставят по любому региону
BACKGROUND = {"region"}

# тема → о чём говорить с менеджером банка
TOPICS = {
    "rate": "структуру долга",
    "deposit_yield": "размещение свободных денег",
    "fx": "валютный риск",
    "ved_logistics": "расчёты с зарубежными партнёрами",
    "commodity_oil": "закупки и цены топлива",
    "gov": "госконтракты и гарантии",
    "consumer": "оборотные деньги под спрос",
    "inflation": "цены и издержки",
    "tax_regulation": "налоговую нагрузку",
    "labor": "фонд оплаты труда",
}


def week_days(now: dt.datetime) -> list[dt.date]:
    today = now.astimezone(MSK).date()
    return [today - dt.timedelta(days=DAYS - 1 - i) for i in range(DAYS)]


def story_key(item: FeedItem) -> str:
    """Тема события: о чём новость больше всего — фактор с самой сильной меткой в разметке (а не самое большое
    слагаемое оценки: «ЦБ не спешит» про ставку, хотя у топливного оптовика больше весит упоминание топлива);
    фактор, названный моделью верха ленты, — главнее; без факторов — «industry:<ОКВЭД>» своей отрасли и
    цепочки."""
    key, _ = main_reason(item)
    if key in BACKGROUND:
        # местное событие с метками и региона, и, например, ставки — в сюжет ставки, а не в фон
        others = [
            t
            for t in item.relevance.breakdown
            if t.kind == "factor" and t.code not in BACKGROUND and about(item, t.code)
        ]
        if others:
            return max(others, key=lambda t: (t.event_strength or 0, t.value)).code
    if key.startswith("chain:"):
        term = next(t for t in item.relevance.breakdown if t.kind == "chain")
        return f"industry:{term.code.split(':')[2]}"
    return key or "other"


def _tagged(event: NewsEvent, key: str, aliases: dict[str, str]) -> bool:
    if key.startswith("industry:"):
        okved = key.split(":", 1)[1]
        return any(o == okved and s >= TAG_MIN for o, s in event.sectors)
    return any(aliases.get(c, c) == key and s >= TAG_MIN for c, s, _ in event.factors)


def topic_counts(
    events: Iterable[NewsEvent], key: str, days: list[dt.date], aliases: dict[str, str]
) -> list[int]:
    """Сколько новостей недели о теме — по дням (от 6 дней назад до сегодня)."""
    counts = [0] * len(days)
    index = {d: i for i, d in enumerate(days)}
    for event in events:
        if event.published_at is None or not _tagged(event, key, aliases):
            continue
        i = index.get(event.published_at.astimezone(MSK).date())
        if i is not None:
            counts[i] += 1
    return counts


def dynamics(counts: list[int]) -> str:
    """По среднему в день: первые 4 дня против последних 3. appeared — раньше новостей не было; grew — к концу
    недели в день на четверть больше; faded — на четверть меньше; steady — ровный поток."""
    early, late = sum(counts[:4]) / 4, sum(counts[4:]) / 3
    if early == 0:
        return "appeared" if late > 0 else "steady"
    if late >= early * (1 + DYNAMICS_GAP):
        return "grew"
    return "faded" if late <= early * (1 - DYNAMICS_GAP) else "steady"


def _date(item: FeedItem) -> dt.date | None:
    published = item.source.published_at
    return published.astimezone(MSK).date() if published else item.event.date


def _on_topic(item: FeedItem, key: str) -> bool:
    """В сюжет — только новости, где тема главная по разметке (метка от 0,5) или её назвала модель:
    побочное упоминание («Мигранты» с меткой спроса рядом со Skoda) сюжет не размывает."""
    if key == "other":  # метки не по смыслу — не сюжет
        return False
    if key.startswith("industry:"):
        return True
    terms = item.relevance.breakdown
    if any(t.kind == "llm" and t.code == f"llm:{key}" for t in terms):
        return True
    # сила метки не указана (старый снимок ленты) — не отсекаем
    return any(
        t.kind == "factor" and t.code == key and (t.event_strength is None or t.event_strength >= TAG_MIN)
        for t in terms
    )


def story_title(key: str, best: FeedItem, exposure: ExposureMap | None) -> str:
    """Свой заголовок сюжета, а не шутливый заголовок СМИ: последствие для компании («Ставка продержится
    дольше»); направление не определить — тема и суть главной новости («Курс валют: …»)."""
    known = consequence(best, key, exposure)
    if known:
        head = known.split(" — ")[0]
        return head[:1].upper() + head[1:]
    labels = {f.code: f.label for f in exposure.factors} if exposure else {}
    label = labels.get(key) or ("Ваша отрасль" if key.startswith("industry:") else None)
    return f"{label}: {gist(best)}" if label else gist(best)


def build_stories(
    items: list[FeedItem],
    events: list[NewsEvent],
    days: list[dt.date],
    aliases: dict[str, str],
    exposure: ExposureMap | None = None,
) -> list[Story]:
    """Сюжеты недели по убыванию значимости: сначала важные и «следить», не больше пяти, не меньше трёх."""
    groups: dict[str, list[FeedItem]] = {}
    week = set(days)
    for item in sorted(items, key=lambda i: -i.relevance.score):
        if item.relevance.breakdown and _date(item) in week and (key := story_key(item)) not in BACKGROUND:
            if _on_topic(item, key):
                groups.setdefault(key, []).append(item)
    stories = []
    for key, group in groups.items():
        best = group[0]
        counts = topic_counts(events, key, days, aliases)
        if not any(counts):  # тему держат только слабые метки — считаем события сюжета
            counts = [sum(1 for i in group if _date(i) == d) for d in days]
        peak = _peak(group, events, key, days, counts, aliases)
        stories.append(
            Story(
                code=key,
                title=story_title(key, best, exposure),
                level=best.takeaway.level if best.takeaway else "info",
                dynamics=dynamics(counts),
                daily_counts=counts,
                news_count=sum(counts),
                peak=peak,
                takeaway=best.takeaway,
                event_ids=[i.event_id for i in group],
            )
        )
    important = [s for s in stories if s.level != "info"]
    rest = [s for s in stories if s.level == "info"]
    chosen = important[:STORIES_MAX]
    return chosen + rest[: max(0, STORIES_MIN - len(chosen))]


def _peak(
    group: list[FeedItem],
    events: list[NewsEvent],
    key: str,
    days: list[dt.date],
    counts: list[int],
    aliases: dict[str, str],
) -> Peak | None:
    """День с наибольшим числом новостей темы и что в этот день случилось: событие сюжета этого дня, иначе
    новость темы этого дня с самой сильной меткой — дата и «что» всегда про один день."""
    if not any(counts):
        return None
    day = days[max(range(len(days)), key=lambda i: (counts[i], i))]
    top = next((i for i in group if _date(i) == day), None)
    if top is not None:
        return Peak(date=day, what=gist(top), event_id=top.event_id)
    same_day = [
        e
        for e in events
        if e.published_at and e.published_at.astimezone(MSK).date() == day and _tagged(e, key, aliases)
    ]
    if not same_day:
        return None
    news = max(
        same_day, key=lambda e: max((s for c, s, _ in e.factors if aliases.get(c, c) == key), default=0)
    )
    return Peak(date=day, what=news.title.split(" // ")[0], event_id=news.id)


def lead_story(stories: list[Story]) -> Story | None:
    """Главный сюжет недели — первый важный или «следить» с темой, о которой есть что обсудить с банком;
    по нему и позиция банка, и главное действие."""
    return next((s for s in stories if s.level != "info" and s.code in TOPICS), None)


def main_action(stories: list[Story]) -> MainAction | None:
    """Главное действие — обсудить с менеджером тему главного сюжета."""
    lead = lead_story(stories)
    if lead is None:
        return None
    topic = TOPICS[lead.code]
    return MainAction(
        code=lead.code, topic=topic, label=f"Обсудить {topic} с менеджером", event_id=lead.event_ids[0]
    )
