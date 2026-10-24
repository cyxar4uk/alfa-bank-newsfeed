"""Цикл агента интерпретации: план → инструменты → черновик → самопроверка → доработка (не больше двух
кругов).

Агентная логика своя, без фреймворков. Модель решает, какие факторы и каналы проверить и что искать;
инструменты приносят данные; модель пишет черновик; детерминированная самопроверка ищет нарушения правил; при
проблемах агент доискивает аналитику и просит модель исправить черновик. Что так и не прошло проверку —
убирается из карточки, а в `quality.warnings` честно написано, чего не хватило.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from api.agent.checks import Checker, Report, quote_in
from api.agent.context import AgentContext
from api.agent.drafts import Draft, Plan, cited, to_statement
from api.agent.forecasts import FORECASTS, TOPICS_BY_FACTOR
from api.agent.numbers import numbers_in
from api.agent.plain import humanize_note, is_plain, ru_decimals
from api.agent.ports import CompanyData, Event, Library
from api.agent.prompts import draft_messages, plan_messages, revise_messages
from api.agent.relevance import combine as relevance_combine
from api.agent.relevance import formula as relevance_formula
from api.agent.relevance import terms_for as relevance_terms
from api.agent.tools import BANK_RATE, Tools, event_factor_codes
from api.agent.trace import TOOL_STAGES, ProgressStep, TraceRecorder
from api.contract import (
    Action,
    BankPosition,
    Consequences,
    Insight,
    InsightEvent,
    Persona,
    Quality,
    Quote,
    Relevance,
    Source,
    Trace,
    Verdict,
)
from api.llm import BudgetExceeded, LlmClient, LlmError

MAX_REVISIONS = 2
MAX_ANALYTICS_QUERIES = 4
# рассуждения DeepSeek занимают 4–7 тыс. токенов до ответа; меньший предел обрезает JSON и стоит лишней
# попытки
DRAFT_MAX_TOKENS = 8000  # без рассуждений черновик — 3–5 тыс. токенов


class AgentError(RuntimeError):
    """Агент не смог собрать карточку: нет данных о компании или модель не ответила.

    `trace` — трасса до места сбоя: её сохраняют, чтобы было видно, на каком шаге и сколько потрачено.
    """

    def __init__(self, message: str, trace: Trace | None = None) -> None:
        super().__init__(message)
        self.trace = trace


class CompanyNotFound(AgentError):
    """У пользователя нет компании в данных банка."""


@dataclass
class Result:
    insight: Insight
    trace: Trace
    context: AgentContext
    cost: float


def insight_id(event_id: str, persona_id: str) -> str:
    return "ins:" + hashlib.sha256(f"{event_id}|{persona_id}".encode()).hexdigest()[:16]


class Agent:
    def __init__(self, llm: LlmClient, company: CompanyData, library: Library) -> None:
        self.llm = llm
        self.company = company
        self.library = library

    # --- шаги -------------------------------------------------------------------------------------

    def gather(self, persona: Persona, event: Event, trace: TraceRecorder) -> tuple[AgentContext, Tools]:
        trace.stage(TOOL_STAGES["get_profile"])
        profile = self.company.profile(persona.company_id)
        if profile is None:
            raise CompanyNotFound(f"нет данных о компании {persona.company_id}")
        trace.found(persona.company_name or "")
        trace.tool(
            "get_profile", {"company_id": profile.id}, [f.id for f in profile.features], profile.display_name
        )
        ctx = AgentContext(persona=persona, profile=profile, event=event)
        if event.warnings:
            # например, в тексте своей новости фразы, похожие на команды модели: это данные, их не выполняем
            ctx.warnings += event.warnings
            trace.check(True, "разбор новости: " + "; ".join(event.warnings))
        tools = Tools(self.company, self.library, trace)
        tools.exposure_map(ctx)
        return ctx, tools

    def plan(self, ctx: AgentContext, trace: TraceRecorder) -> Plan:
        completion = self.llm.complete("plan", plan_messages(ctx), schema=Plan, max_tokens=1500)
        trace.llm("plan", completion.calls)
        plan = completion.value
        known = {f.code for f in ctx.exposure}
        plan.factors = [f for f in plan.factors if f.code in known] or plan.factors
        trace.plan(
            "факторы: "
            + ", ".join(f"{f.code} — {f.why}" for f in plan.factors)
            + f"; каналы: {', '.join(plan.channels) or 'нет'}; аналитика: {'; '.join(plan.analytics_queries)}"
            + (f"; новости: {'; '.join(plan.news_queries)}" if plan.news_queries else "")
            + f"; роль: {plan.role_focus}"
        )
        return plan

    def execute(self, ctx: AgentContext, tools: Tools, plan: Plan) -> None:
        factor_codes = [f.code for f in plan.factors]
        # цепочку смотрим всегда: без неё самопроверка не отличит реальных контрагентов от выдуманных
        tools.counterparty_chain(ctx)
        # группу смотрим всегда, когда она есть: через неё часто идёт второй канал (кредиты, ВЭД участников)
        if ctx.profile.group is not None and ctx.profile.group.size > 1:
            tools.group_impact(ctx)
        for query in plan.analytics_queries[:MAX_ANALYTICS_QUERIES]:
            tools.search_alfa_analytics(ctx, query, factor_codes)
        # и по самому событию: запросы плана бывают слишком общими («прогноз инфляции»)
        tools.search_alfa_analytics(ctx, ctx.event.source.title[:160], factor_codes)
        # по ставке, курсу и инфляции — всегда самый свежий прогноз банка, чтобы старый не выдать за
        # актуальный
        codes = {*event_factor_codes(ctx.event), *factor_codes}
        topics = {TOPICS_BY_FACTOR[c] for c in codes if c in TOPICS_BY_FACTOR}
        for forecast in FORECASTS:
            if forecast.topic in topics:
                tools.search_alfa_analytics(ctx, forecast.query, None, material=forecast.material)
        for query in plan.news_queries[:2]:
            tools.search_news(ctx, query, factor_codes)
        if plan.need_estimates or set(event_factor_codes(ctx.event)) & {"rate", "deposit_yield", "fx"}:
            tools.estimate_rate_impact(ctx)
        tools.products_for_risk(ctx)
        tools.load_pages(ctx, {h.page_ref for h in ctx.analytics})

    def draft(self, ctx: AgentContext, trace: TraceRecorder) -> Draft:
        completion = self.llm.complete(
            "draft", draft_messages(ctx), schema=Draft, max_tokens=DRAFT_MAX_TOKENS
        )
        trace.llm("draft", completion.calls)
        return completion.value

    def check(self, ctx: AgentContext, draft: Draft, trace: TraceRecorder) -> Report:
        report = Checker(ctx).run(draft)
        trace.check(report.ok, report.summary())
        return report

    def dig(self, ctx: AgentContext, tools: Tools, report: Report, plan: Plan) -> str:
        """Доискать, если не хватает данных: позиции банка или второго фактора."""
        notes = []
        checks = {i.check for i in report.issues}
        if "bank_quotes" in checks and not ctx.analytics:
            codes = [f.code for f in plan.factors] or event_factor_codes(ctx.event)
            query = ctx.event.source.title[:120]
            added = tools.search_alfa_analytics(ctx, query, codes)
            if added:
                tools.load_pages(ctx, {h.page_ref for h in ctx.analytics})
                notes.append(f"Доискал аналитику банка по заголовку события: +{added} фрагментов.")
        if "multi_factor" in checks and not ctx.news:
            codes = [f.code for f in plan.factors] or event_factor_codes(ctx.event)
            tools.search_news(ctx, ctx.event.source.title[:120], codes)
            if ctx.news:
                notes.append(f"Доискал связанные новости: +{len(ctx.news)}.")
        return " ".join(notes)

    # --- сборка -----------------------------------------------------------------------------------

    def run(
        self,
        persona: Persona,
        event: Event,
        on_progress: Callable[[list[ProgressStep]], None] | None = None,
    ) -> Result:
        """Собрать карточку. `on_progress(шаги)` — ход разбора по мере работы, для статуса пользователю."""
        trace = TraceRecorder(on_progress=on_progress)
        try:
            result = self._run(persona, event, trace)
            trace.finish(ok=True)
            return result
        except (LlmError, BudgetExceeded) as exc:
            trace.finish(ok=False)
            trace.llm("ошибка", exc.calls)
            trace.check(False, f"агент остановлен: {exc}")
            raise AgentError(str(exc), trace.trace) from exc
        except AgentError as exc:
            trace.finish(ok=False)
            exc.trace = trace.trace
            raise
        except Exception as exc:
            trace.finish(ok=False)
            # любой другой сбой (данные, разметка) — с трассой до места сбоя, без подробностей наружу
            trace.check(False, f"агент остановлен: внутренняя ошибка {type(exc).__name__}")
            raise AgentError("внутренняя ошибка агента", trace.trace) from exc

    def _run(self, persona: Persona, event: Event, trace: TraceRecorder) -> Result:
        ctx, tools = self.gather(persona, event, trace)
        trace.stage("Решаю, что проверить в первую очередь")
        plan = self.plan(ctx, trace)
        trace.found(plan.role_focus)
        self.execute(ctx, tools, plan)
        trace.stage("Формулирую вывод: важно ли это вам и что делать")
        draft = self.draft(ctx, trace)
        trace.stage("Сверяю каждую цифру и цитату с источниками")
        report = self.check(ctx, draft, trace)
        trace.found(_check_found(report))
        best = (draft, report)
        for n in range(1, MAX_REVISIONS + 1):
            if not _worth_revising(ctx, report, n):
                break
            extra = self.dig(ctx, tools, report, plan)
            trace.retry(f"круг {n}: {len(report.issues)} проблем(ы). {extra}".strip())
            trace.stage(f"Исправляю неточности (круг {n} из {MAX_REVISIONS})")
            try:
                completion = self.llm.complete(
                    "revise",
                    revise_messages(ctx, draft, report, extra),
                    schema=Draft,
                    max_tokens=DRAFT_MAX_TOKENS,
                )
            except LlmError as exc:
                # доработка не удалась (обрыв, сбой модели) — карточка из лучшего черновика, а не ошибка
                trace.llm("revise", exc.calls)
                trace.check(False, f"доработка не удалась: {exc}; карточка — из лучшего черновика")
                break
            trace.llm("revise", completion.calls)
            draft = completion.value
            report = self.check(ctx, draft, trace)
            trace.found(_check_found(report))
            # доработка могла выйти хуже — дальше работаем с лучшим из черновиков, он же идёт в карточку
            if _badness(report) <= _badness(best[1]):
                best = (draft, report)
            draft, report = best
        insight = self.assemble(ctx, draft, report, trace)
        return Result(insight=insight, trace=trace.trace, context=ctx, cost=trace.cost)

    def assemble(self, ctx: AgentContext, draft: Draft, report: Report, trace: TraceRecorder) -> Insight:
        clean = _without(draft, report)
        dropped = len(draft.statements()) - len(clean.statements()) + len(draft.actions) - len(clean.actions)
        final = Checker(ctx).run(clean)
        # значимость — согласованная с объяснением: формальная оценка и факторы, на которых строится карточка
        formal = self.company.relevance(ctx.persona, ctx.event.source) or relevance_formula(ctx)
        checker = Checker(ctx)
        terms = relevance_terms(ctx, checker.covered_factors(clean), checker.stated_factors(clean))
        score, basis = relevance_combine(formal, terms)
        trace.tool(
            "relevance",
            {"formal": formal.score},
            [],
            f"итог {score:.2f} — {basis}; " + "; ".join(t.describe() for t in terms[:5]),
        )
        trace.check(final.ok, f"итог после очистки (убрано {dropped}): " + final.summary())
        sources = ctx.sources()

        used_sources: dict[str, Source] = {}
        quotes: dict[str, list[str]] = {}
        cited_refs = [
            (cited(s), s.quote if s.origin in ("fact", "bank") else None) for _, _, s in clean.statements()
        ]
        if clean.verdict:
            cited_refs.append((clean.verdict.refs, None))
        if clean.bank_position:
            cited_refs.append((clean.bank_position.refs, clean.bank_position.quote))
        for refs_, quote in cited_refs:
            for ref in refs_:
                if ref.startswith("src:"):
                    src = sources.get(ref) or sources.get(ref.split("#", 1)[0]) or _page_of(ctx, ref)
                    if src is not None:
                        used_sources.setdefault(src.id, src)
                    if quote:
                        quotes.setdefault(src.id if src else ref, []).append(quote.strip())

        consequences = Consequences(
            risks=[to_statement(s) for s in clean.risks],
            opportunities=[to_statement(s) for s in clean.opportunities],
            factors=[to_statement(s) for s in clean.watch],
        )
        for est in ctx.estimates:
            getattr(consequences, est.place).append(est.statement)
            for ref in est.statement.refs:
                if ref.startswith("src:alfa:") and ref not in used_sources:
                    used_sources[ref] = _page_source(ref, ctx.page_texts.get(ref, ""))

        actions = [Action(text=ru_decimals(a.text), kind=a.kind, refs=a.refs) for a in clean.actions]
        if ctx.offer:
            actions.append(
                Action(text=ctx.offer.text, kind="product", product=ctx.offer.product, refs=ctx.offer.refs)
            )

        # фрагмент материала в карточке — дословная выдержка, которую сверила самопроверка
        out_sources = []
        for sid, src in used_sources.items():
            src = src.model_copy()
            if src.kind == "alfa_analytics" and quotes.get(sid):
                src.fragment = " … ".join(dict.fromkeys(quotes[sid]))
            out_sources.append(src)
        if ctx.event.id not in used_sources:
            out_sources.insert(0, ctx.event.source)

        refs = {r for _, _, s in clean.statements() for r in cited(s)}
        refs |= {r for e in ctx.estimates for r in e.statement.refs} | {r for a in actions for r in a.refs}
        refs |= set(clean.relevance_refs)
        refs |= set(clean.verdict.refs) if clean.verdict else set()
        known = ctx.feature_ids()
        features_used = sorted(r for r in refs if r.startswith("feat:") and r in known)

        raw = list(dict.fromkeys([*ctx.warnings, *clean.warnings, *report.warnings]))
        if not clean.bank_view and not clean.bank_position and not any(not h.stale for h in ctx.analytics):
            raw.append("позиции Альфа-Банка по теме нет")
        if dropped:
            raw.append(f"убрано утверждений, которые не подтвердились источниками: {dropped}")
        for issue in final.issues:
            note = SOFT_NOTES.get(issue.check)
            if not issue.hard and note:
                raw.append(note)
        # пользователь видит только предупреждения человеческим языком; служебные — в трассе
        shown = {w: humanize_note(w) for w in dict.fromkeys(raw)}
        warnings = list(dict.fromkeys(h for h in shown.values() if h))
        hidden = [w for w, h in shown.items() if not h]
        if hidden:
            trace.check(True, "служебные предупреждения (не показаны): " + "; ".join(hidden))

        reason = next(
            (r for r in (clean.relevance_reason, formal.reason) if r and is_plain(r)),
            "событие касается того, от чего зависит бизнес компании",
        )
        relevance = Relevance(
            score=score,
            reason=reason,
            refs=[r for r in dict.fromkeys([*formal.refs, *clean.relevance_refs]) if r in known],
        )
        published = ctx.event.source.published_at
        insight = Insight(
            id=insight_id(ctx.event.id, ctx.persona.id),
            event=InsightEvent(title=ctx.event.source.title, date=published.date() if published else None),
            relevance=relevance,
            what_happened=[to_statement(s) for s in clean.what_happened],
            why_it_matters=[to_statement(s) for s in clean.why_it_matters],
            consequences=consequences,
            bank_view=[to_statement(s) for s in clean.bank_view],
            actions=actions,
            sources=out_sources,
            features_used=features_used,
            quality=Quality(checks_passed=final.passed, warnings=warnings),
            trace_id=trace.id,
            verdict=_verdict(clean, score, reason, actions),
            bank_position=_bank_position(ctx, clean),
            quotes=_quotes(ctx, clean),
        )
        missing = insight.unresolved_refs()
        if missing:
            # не должно случаться после самопроверки; если случилось — не отдаём битые ссылки молча
            trace.check(False, f"ссылки без источника: {', '.join(sorted(missing)[:5])}")
            insight.quality.warnings.append("часть ссылок на источники не удалось проверить")
            insight.quality.checks_passed = [c for c in insight.quality.checks_passed if c != "refs"]
        return insight


# мягкие проблемы самопроверки — пользователю человеческим языком; остальные — только в трассе
SOFT_NOTES = {
    "multi_factor": "Событие касается компании только с одной стороны — другие связи в данных не видны",
    "role": "Не всё в разборе удалось привязать к задачам вашей роли",
    "bank_quotes": "Позицию Альфа-Банка по этой теме подтвердить материалом не удалось",
}
NO_BANK_POSITION = (
    "Альфа-Банк не публиковал позицию по этой теме — вывод сделан по данным о компании и новости"
)
UNCONFIRMED_BANK_POSITION = "Позицию Альфа-Банка по этой теме подтвердить материалом не удалось"


def _verdict(draft: Draft, score: float, reason: str, actions: list[Action]) -> Verdict:
    """Итог из черновика; если модель его не дала или он не прошёл проверку — по оценке и выводам карточки."""
    v = draft.verdict
    if v is not None:
        return Verdict(
            level=v.level,
            headline=ru_decimals(v.headline),
            why=ru_decimals(v.why),
            actions=[ru_decimals(a) for a in v.actions[:3]],
            refs=list(dict.fromkeys(v.refs)),
        )
    level = "act" if score >= 0.5 else "watch" if score >= 0.2 else "info"
    headline = {
        "act": "Для вас важно: событие задевает деньги или ключевых контрагентов компании",
        "watch": "Стоит следить: влияние на компанию возможно, но не прямое",
        "info": "На вашу компанию почти не влияет",
    }[level]
    plain = [s.text for s in draft.why_it_matters if s.origin == "data" and is_plain(s.text)]
    why = next((t for t in plain if numbers_in(t)), plain[0] if plain else reason)
    steps = (
        [a.text for a in actions if a.kind != "product" and is_plain(a.text)][:3] if level != "info" else []
    )
    return Verdict(level=level, headline=headline, why=why, actions=steps)


def _cited_hit(ctx: AgentContext, refs: list[str], quote: str | None):
    """Фрагмент аналитики, на который опирается позиция: где найдена её цитата, а не первый попавшийся.

    Возвращает (ссылка, фрагмент). Подпись (материал, дата) берётся из него же — иначе фраза из одного
    материала подписывается другим.
    """
    checker = Checker(ctx)
    alfa = [r for r in refs if r.startswith("src:alfa:")]
    quoted = [r for r in alfa if quote and quote_in(quote, checker.source_text(r))]
    for ref in [*quoted, *alfa]:
        page = ctx.page_ref_of(ref) or ref
        hit = next((h for h in ctx.analytics if ref in (h.source.id, h.page_ref) or h.page_ref == page), None)
        if hit is not None:
            return ref, hit
    return (alfa[0] if alfa else None), None


def _bank_position(ctx: AgentContext, draft: Draft) -> BankPosition:
    """Позиция банка одной фразой с материалом и датой; нет позиции — так и сказано."""
    bp = draft.bank_position
    if bp is not None:
        statement, refs, quote = bp.statement, bp.refs, bp.quote
    elif draft.bank_view:
        first = draft.bank_view[0]
        statement, refs, quote = first.text, first.refs, first.quote
    elif any(not h.stale for h in ctx.analytics):
        # материал банка был, но позиция не подтвердилась самопроверкой — это не «банк не публиковал»
        return BankPosition(found=False, statement=UNCONFIRMED_BANK_POSITION)
    else:
        return BankPosition(found=False, statement=NO_BANK_POSITION)
    cited, hit = _cited_hit(ctx, refs, quote)
    return BankPosition(
        found=True,
        statement=ru_decimals(statement),
        # имени аналитика в распознанных материалах нет — не выдумываем
        analyst=None,
        material=hit.source.title if hit else None,
        date=hit.material_date if hit else None,
        source_id=cited or (hit.source.id if hit else None),
        url=hit.source.url if hit else None,
    )


def _quotes(ctx: AgentContext, draft: Draft) -> list[Quote]:
    """Дословные выдержки из новости, на которые опираются факты карточки, — для подсветки в полном тексте."""
    out: list[Quote] = []
    for s in draft.what_happened + draft.why_it_matters + draft.watch:
        if s.origin != "fact" or not s.quote or ctx.event.id not in s.refs:
            continue
        text = s.quote.strip()
        if quote_in(text, ctx.event.text) and all(q.text != text for q in out):
            out.append(Quote(text=text, source_id=ctx.event.id))
    return out


def _check_found(report: Report) -> str:
    hard = sum(1 for i in report.issues if i.hard)
    if not report.issues:
        return "Всё сходится с источниками"
    if hard:
        return f"Не подтвердилось утверждений: {hard} — исправляю или убираю"
    return "Цифры и цитаты сходятся, уточняю формулировки"


def _badness(report: Report) -> tuple[int, int]:
    return (sum(1 for i in report.issues if i.hard), len(report.issues))


def _worth_revising(ctx: AgentContext, report: Report, round_no: int) -> bool:
    """Дорабатывать, только если есть что исправить: жёсткие проблемы или исправимые мягкие.

    Двух факторов не станет, если их нет в данных; позицию банка не стоит выжимать из нерелевантной аналитики
    дважды — после первого круга такие проблемы остаются предупреждениями.

    Второй круг — полный черновик заново (~0,2 ₽, ~15 с) — только ради итога, позиции банка или нескольких
    неподтверждённых утверждений: одно такое утверждение дешевле убрать из карточки, чем переписывать всё.
    """
    if round_no > 1:
        hard = report.hard_at()  # утверждения, а не проблемы: у одного их бывает несколько
        if len(hard) < 2 and not any(i.block == "verdict" and i.hard for i in report.issues):
            return False
    for issue in report.issues:
        if issue.hard:
            return True
        if issue.check == "multi_factor" and len(ctx.factor_codes()) < 2:
            continue
        if issue.check == "bank_quotes" and round_no > 1:
            continue
        return True
    return False


def _page_of(ctx: AgentContext, ref: str) -> Source | None:
    """Источник для ссылки на страницу материала (`#p2` без номера фрагмента) — по найденному фрагменту."""
    hit = next((h for h in ctx.analytics if h.page_ref == ref), None)
    return hit.source.model_copy(update={"id": ref}) if hit else None


def _without(draft: Draft, report: Report) -> Draft:
    """Черновик без утверждений и действий с неисправленными жёсткими проблемами."""
    bad = report.hard_at()
    data = draft.model_copy(deep=True)
    for block in ("what_happened", "why_it_matters", "risks", "opportunities", "watch", "bank_view"):
        items = getattr(data, block)
        setattr(data, block, [s for i, s in enumerate(items) if (block, i) not in bad])
    data.actions = [a for i, a in enumerate(data.actions) if ("actions", i) not in bad]
    if ("verdict", 0) in bad:
        data.verdict = None
    if ("bank_position", 0) in bad:
        data.bank_position = None
    return data


def _page_source(ref: str, page_text: str) -> Source:
    m = re.search(r"#p(\d+)", ref)
    snippet = ""
    for number in BANK_RATE["pages"].get(ref, []):
        pos = page_text.replace("\n", " ").find(number)
        if pos >= 0:
            flat = page_text.replace("\n", " ")
            snippet = flat[max(0, pos - 120) : pos + 60].strip()
            break
    return Source(
        id=ref,
        kind="alfa_analytics",
        title=BANK_RATE["material"],
        publisher="Альфа-Банк",
        page=int(m.group(1)) if m else None,
        fragment=snippet or None,
    )
