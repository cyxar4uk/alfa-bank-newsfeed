"""Операции над данными компании — общие для эндпоинтов и инструментов агента.

На вход — репозиторий (`CompanyRepo`) и id компании, на выход — модели контракта; нет компании — None.
"""

import datetime as dt

from api.bankview import bank_view
from api.chain import MIN_SHARE, build_chain
from api.contract import (
    CompanyProfile,
    ExposureMap,
    Feed,
    FeedItem,
    FeedRelevance,
    GroupImpact,
    InfluenceChain,
    InsightEvent,
    RiskMap,
)
from api.coverage import coverage_in, event_coverage
from api.exposure import build_exposure
from api.group import group_context
from api.images import proxied
from api.levels import LEVELS
from api.news import NewsProvider
from api.personas import parse_persona_id
from api.profile import GROUP_MEMBERS_SHOWN, build_profile, countries
from api.ranking import MSK, NewsEvent, default_ranking, rank
from api.records import CompanyRecord, Flow
from api.repo import CompanyRepo
from api.riskmap import limits, order, risk_factor
from api.takeaway import takeaways
from api.week import DAYS, build_stories, lead_story, main_action, week_days

# роли, которым в ленте показывается влияние на группу
GROUP_ROLES = {"owner", "ceo"}


def company_profile(repo: CompanyRepo, company_id: str) -> CompanyProfile | None:
    company = repo.get_company(company_id)
    if company is None:
        return None
    size, members, group_revenue = 1, [], None
    if company.group_id:
        size, members = repo.group(company.group_id, exclude=company.id, limit=GROUP_MEMBERS_SHOWN)
        stats = repo.group_stats([company.group_id]).get(company.group_id)
        group_revenue = stats.revenue if stats else None
    return build_profile(
        company,
        repo.flows(company.id),
        group_size=size,
        group_members=members,
        industry=repo.industry(company),
        group_revenue=group_revenue,
    )


def company_exposure(repo: CompanyRepo, company_id: str) -> ExposureMap | None:
    company = repo.get_company(company_id)
    if company is None:
        return None
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    return build_exposure(company, repo.flows(company.id), group)


def company_chain(
    repo: CompanyRepo, company_id: str, okved: list[str], weights: dict[str, float] | None = None
) -> InfluenceChain | None:
    """Через кого событие с классами ОКВЭД `okved` задевает компанию.

    `weights` — сила связи события с классом ОКВЭД (0–1), по умолчанию 1.
    """
    company = repo.get_company(company_id)
    if company is None:
        return None
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    return build_chain(company, repo.flows(company.id), group, okved, weights)


def ved_countries(company: CompanyRecord, group: list[CompanyRecord], flows: list[Flow]) -> set[str] | None:
    """Страны ВЭД компании, её группы и заметных контрагентов (от 1 % оборота) — через них зарубежное событие
    задевает компанию. ВЭД есть, а страны не указаны — None: связь с любой страной возможна."""
    if company.fts_flag and not company.fts_countries:
        return None
    turnover = sum(f.amount for f in flows)
    major = [
        f.counterparty for f in flows if f.counterparty and turnover and f.amount >= MIN_SHARE * turnover
    ]
    return {c for r in [company, *group, *major] if r.fts_countries for c in countries(r.fts_countries)}


def persona_feed(
    repo: CompanyRepo,
    news: NewsProvider,
    persona: str,
    limit: int = 20,
    candidates: int = 500,
    days: int = 90,
    now: dt.datetime | None = None,
    query: str | None = None,
    events: list[NewsEvent] | None = None,
) -> Feed | None:
    """Лента пользователя: события, задевающие его компанию, по убыванию оценки с учётом роли.

    Пользователь — `p-u<номер компании>-<роль>`; компания должна быть действующим клиентом банка (сервис — для
    клиентов), иначе — None. Так ленту можно открыть для любого клиента, не только из `/api/personas`.
    `query` — поиск: новости по запросу в том же формате; задевающие компанию — первыми, остальные следом
    с оценкой 0 («к сведению»). `events` — уже загруженные события вместо выборки за `days` дней.
    """
    parsed = parse_persona_id(persona)
    if parsed is None:
        return None
    company_id, role = parsed
    company = repo.get_company(company_id)
    if company is None or company.client_type != "CLIENT":
        return None
    now = now or dt.datetime.now(MSK)
    flows = repo.flows(company.id)
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    exposure = build_exposure(company, flows, group)
    if events is not None:
        pass  # события уже загружены (неделя: те же события идут и в счётчики тем)
    elif query is not None:
        events = news.search(query, limit=candidates)
    else:
        events = news.events(since=now - dt.timedelta(days=days), limit=candidates)
    items = rank(
        events,
        exposure,
        lambda okved, weights: build_chain(company, flows, group, okved, weights),
        role,
        now,
        bank_view=news.has_bank_view,
        regions={r for r in (company.region, company.city) if r},
        countries=ved_countries(company, group, flows),
    )
    if query is not None:
        ranked = {i.event_id for i in items}
        items += [unrelated_item(e) for e in events if e.id not in ranked]
    items = items[:limit]
    # охват в группе — то же число, что получает агент (api.coverage); блок «Ваша группа» в ответе —
    # собственнику и гендиректору, а число в выводе — всем ролям
    if ctx := group_context(company, group, flows):
        by_id = {e.id: e for e in events}
        for item in items:
            event = by_id.get(item.event_id)
            if event is None:
                continue
            item.coverage = coverage_in(
                ctx, company, flows, group, [(c, s) for c, s, _ in event.factors], event.sectors
            )
            if role in GROUP_ROLES:
                item.group_impact = item.coverage
    takeaways(items, role, exposure)  # после охвата: вывод берёт из него число
    return Feed(
        persona_id=persona,
        company_id=company.id,
        role=role,
        items=items,
        candidates=len(events),
        news_source=news.name,
    )


def unrelated_item(event: NewsEvent) -> FeedItem:
    """Найденная поиском новость, которая компанию не задевает: тот же формат, оценка 0."""
    text = "напрямую вашу компанию не задевает"
    date = event.published_at.astimezone(MSK).date() if event.published_at else None
    return FeedItem(
        event_id=event.id,
        event=InsightEvent(title=event.title, date=date),
        relevance=FeedRelevance(score=0, reason=text, refs=[event.id], freshness=1, source_quality=1),
        has_bank_view=False,
        source=event.source(),
        channel="direct",
        channel_text=text,
        image_url=proxied(event.image_url),
        source_icon_url=proxied(event.source_icon_url),
    )


def company_group_impact(
    repo: CompanyRepo,
    company_id: str,
    okved: list[str],
    factors: list[str],
    event: NewsEvent | None = None,
) -> tuple[bool, GroupImpact | None]:
    """Как событие с отраслями `okved` и факторами `factors` задевает группу компании.

    `event` — событие из ленты: его факторы и отрасли с силами из разметки добавляются к `okved` и `factors`
    (у тех сила 1), так блок совпадает с карточкой ленты. (найдена ли компания, влияние); у компании без
    группы влияние — None: блока «Ваша группа» нет.
    """
    company = repo.get_company(company_id)
    if company is None:
        return False, None
    if not company.group_id:
        return True, None
    event_factors = [(c, s) for c, s, _ in event.factors] if event else []
    event_sectors = list(event.sectors) if event else []
    impact = event_coverage(
        repo,
        company.id,
        [*((f, 1.0) for f in factors), *event_factors],
        [*((o, 1.0) for o in okved), *event_sectors],
        keep_empty=True,  # группа есть, событие её не касается — блок с нулём, а не «группы нет»
    )
    return True, impact


WEEK_EVENTS = 2000  # событий недели, не больше (на стенде ≈1300 за неделю): из них и лента, и счётчики тем


def week_events(news: NewsProvider, now: dt.datetime) -> list[NewsEvent]:
    return news.events(since=now - dt.timedelta(days=DAYS), limit=WEEK_EVENTS)


def finish_week(
    feed: Feed,
    events: list[NewsEvent],
    news: NewsProvider,
    now: dt.datetime,
    limit: int,
    exposure: ExposureMap | None = None,
) -> Feed:
    """Неделя поверх ленты за 7 дней: сюжеты, позиция банка по главному сюжету и главное действие."""
    days = week_days(now)
    stories = build_stories(feed.items, events, days, default_ranking().aliases, exposure)
    bank = None
    lead = lead_story(stories)  # одна главная тема: и позиция банка, и действие — о ней
    if lead:
        top = next((i for i in feed.items if i.event_id == lead.event_ids[0]), None)
        date = top.source.published_at.astimezone(MSK).date() if top and top.source.published_at else None
        fragments = getattr(news, "bank_fragments", None)
        bank = bank_view(lead.code, fragments, top.event.title if top else None, date)
    return feed.model_copy(
        update={
            "period": "week",
            "week": days,
            "stories": stories,
            "bank": bank,
            "action": main_action(stories),
            "items": feed.items[:limit],
        }
    )


def company_risk_map(
    repo: CompanyRepo, news: NewsProvider, company_id: str, persona: str, now: dt.datetime | None = None
) -> RiskMap | None:
    """К чему уязвима компания — для роли пользователя `persona`; его компания должна быть `company_id`."""
    parsed = parse_persona_id(persona)
    if parsed is None or parsed[0] != company_id:
        return None
    role = parsed[1]
    now = now or dt.datetime.now(MSK)
    exposure = company_exposure(repo, company_id)
    if exposure is None:
        return None
    events = week_events(news, now)
    feed = persona_feed(repo, news, persona, limit=WEEK_EVENTS, now=now, events=events)
    if feed is not None:  # «сейчас» у фактора — с тем же уровнем, что пользователь видел в ленте
        feed = LEVELS.pin(feed, exposure, remember=False)
    items = feed.items if feed else []
    days = week_days(now)
    aliases = default_ranking().aliases
    bank_fragments = getattr(news, "bank_fragments", None)
    factors = [
        risk_factor(f, items, events, days, exposure, aliases, bank_fragments)
        for f in order(exposure, role, default_ranking())
    ]
    profile = company_profile(repo, company_id)
    coverage = profile.payments.revenue_coverage if profile and profile.payments else None
    return RiskMap(
        company_id=company_id, role=role, week=days, factors=factors, limits=limits(exposure, coverage)
    )
