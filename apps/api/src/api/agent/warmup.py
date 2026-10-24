"""Прогрев карточек для демо: заранее собрать карточки верха ленты демо-пользователей.

Запускать один раз на финальном коде — перед заморозкой и на сервере:

    docker compose exec api python -m api.agent.warmup --top 5          # все демо-пользователи
    docker compose exec api python -m api.agent.warmup --top 1 --personas p-u8318-cfo --dry-run

Карточки кладутся в тот же кэш БД с версией логики агента (`api.agent.version`): после смены промптов или
моделей прогретые карточки не показываются — их надо прогреть заново. Уже собранные карточки той же версии
пропускаются, так что повторный запуск ничего не тратит. Остановка — по лимиту `--budget` (₽ за запуск) и по
суточному стоп-крану клиента моделей.
"""

import argparse
import sys
import time

from psycopg_pool import ConnectionPool

from api.agent.context import AgentContext
from api.agent.loop import insight_id
from api.agent.ports import LEVEL_RANK, Event
from api.agent.relevance import formula
from api.agent.service import AgentService, NotRelevant, build_service
from api.config import get_settings
from api.contract import Insight, Persona
from api.llm import BudgetExceeded
from api.personas import DEMO_COMPANIES, personas_for
from api.repo import PgCompanyRepo


def candidates(service: AgentService, persona: Persona, top: int) -> list[Event]:
    """Верх ленты пользователя: ранжирование, если оно есть в коде, иначе свежие события по факторам карты."""
    feed_fn = _optional_feed()
    if feed_fn is not None:
        feed = feed_fn(persona)
        if feed is not None:
            events = [service.library.get_event(item.event_id) for item in feed.items[: top * 2]]
            return [e for e in events if e is not None][:top]
    # без ранжирования: свежие события по каждому значимому фактору карты, по убыванию формальной оценки
    exposure = service.company.exposure_map(persona.company_id)
    profile = service.company.profile(persona.company_id)
    seen: dict[str, Event] = {}
    for factor in sorted(exposure, key=lambda f: -(f.strength or 0)):
        # спрос и поставки по отраслям (demand_56…) — не факторы разметки новостей, их ищет цепочка
        if LEVEL_RANK.get(factor.level, 0) < 2 or factor.code.startswith(("demand_", "supply_")):
            continue
        try:
            found = service.library.search_news("", factors=[factor.code], limit=10)
        except ValueError:  # фактора нет в словаре разметки новостей
            continue
        for event in found:
            seen.setdefault(event.id, event)
    scored = []
    for event in seen.values():
        if not service.touches(persona, event):
            continue
        ctx = AgentContext(persona=persona, profile=profile, event=event, exposure=exposure)
        ctx.chain = service.company.counterparty_chain(persona.company_id, event.source)
        scored.append((formula(ctx).score, event))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:top]]


_FEED = None


def _optional_feed():
    """Лента из модуля ранжирования (`api.service.persona_feed`), когда он в коде; иначе None."""
    return _FEED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Прогрев карточек верха ленты демо-пользователей")
    ap.add_argument("--top", type=int, default=5, help="сколько событий ленты на пользователя")
    ap.add_argument("--personas", default="", help="id через запятую; по умолчанию — демо-клиенты")
    ap.add_argument("--budget", type=float, default=40.0, help="не тратить за запуск больше, ₽")
    ap.add_argument("--dry-run", action="store_true", help="только показать, какие карточки будут собраны")
    args = ap.parse_args(argv)

    settings = get_settings()
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=4, open=True)
    repo = PgCompanyRepo(pool)
    try:
        from api.search.repo import SearchRepo

        search = SearchRepo(pool)
    except ImportError:
        search = None
    service = build_service(settings, pool, repo, search)
    _wire_feed(repo, search)

    wanted = {p.strip() for p in args.personas.split(",") if p.strip()}
    personas = [
        p for p in personas_for(repo) if (p.id in wanted if wanted else p.company_id in DEMO_COMPANIES)
    ]
    if not personas:
        print("пользователи не найдены", file=sys.stderr)
        return 1
    if service.llm is None and not args.dry_run:
        print("модели не настроены: нет LLM_API_KEY или LLM_BASE_URL", file=sys.stderr)
        return 1

    spent_before = service.llm.budget.spent if service.llm else 0.0
    built = skipped = failed = 0
    print(f"версия логики агента: {service.version}")
    for persona in personas:
        for event in candidates(service, persona, args.top):
            key = insight_id(event.id, persona.id)
            label = f"{persona.id} · {event.source.title[:70]}"
            if service.cached(key) is not None:
                skipped += 1
                print(f"  уже есть  {label}")
                continue
            if args.dry_run:
                print(f"  собрать   {label}")
                continue
            spent = service.llm.budget.spent - spent_before
            if spent >= args.budget:
                print(f"лимит прогрева {args.budget:.0f} ₽ исчерпан — остановлено", file=sys.stderr)
                return _report(built, skipped, failed, spent)
            started = time.monotonic()
            try:
                result = service.insight(event.id, persona.id, wait=True)
            except NotRelevant:
                print(f"  не касается {label}")
                continue
            except BudgetExceeded as exc:
                print(f"стоп: {exc}", file=sys.stderr)
                return _report(built, skipped, failed, service.llm.budget.spent - spent_before)
            except Exception as exc:  # одна неудачная карточка не останавливает прогрев остальных
                failed += 1
                print(f"  ошибка    {label}: {exc}")
                continue
            if not isinstance(result, Insight):  # её ещё собирает API — не считаем собранной
                failed += 1
                print(f"  не дождался {label}: {result.status} {result.stage or result.error or ''}")
                continue
            built += 1
            print(f"  собрано   {label} · {time.monotonic() - started:.0f} с")
    spent = (service.llm.budget.spent - spent_before) if service.llm else 0.0
    return _report(built, skipped, failed, spent)


def _wire_feed(repo, search) -> None:
    global _FEED
    try:
        from api.service import persona_feed  # появится с модулем ранжирования (#8)
    except ImportError:
        return
    if search is None:
        return
    try:
        from api.news import SearchNews  # провайдер новостей ранжирования

        news = SearchNews(search)
    except ImportError:
        return
    _FEED = lambda persona: persona_feed(repo, news, persona.id, limit=20)  # noqa: E731


def _report(built: int, skipped: int, failed: int, spent: float) -> int:
    print(f"собрано {built}, уже было {skipped}, ошибок {failed}, потрачено {spent:.2f} ₽")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
