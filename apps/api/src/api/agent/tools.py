"""Инструменты агента: обёртки над модулями профиля и поиска плюс свои расчёты.

Каждый вызов инструмента — шаг трассы: что спросили, какие источники и признаки вернулись. Так по трассе
видно, на чём основан вывод (критерий 11), а журнал обращений к инструментам — часть безопасности (ограничение
4): агент может только читать данные этой компании и материалы, других действий у него нет.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from api.agent.context import AgentContext, Estimate, Offer
from api.agent.ports import LEVEL_RANK, AnalyticsHit, CompanyData, Event, Library
from api.agent.trace import TOOL_STAGES, TraceRecorder
from api.contract import Statement

PRODUCTS_FILE = Path(__file__).with_name("products.toml")

# Прогноз ключевой ставки Альфа-Банка — материал «Ключевая ставка ЦБ РФ…» от 11.09.2026 (самый свежий).
# Цифры сверяются с распознанным текстом страниц перед расчётом: не нашлись — расчёта нет.
BANK_RATE = {
    "current": 14.0,
    "end_2026": 14.0,
    "end_2027": 12.0,
    "previous_end_2026": 13.5,
    "material": "«Ключевая ставка ЦБ РФ: ставка без изменения на 14,0 %, риторика стала жестче», 11.09.2026",
    # прогноз целиком — в тексте первой страницы; таблица на второй распознаётся с ошибками
    "pages": {"src:alfa:keyrate-2026-09#p1": ["14,0%", "13,5%", "12,0%"]},
}


@dataclass
class ProductRule:
    factor: str
    product: str
    name: str
    feature: str
    has_text: str
    new_text: str
    roles: list[str]

    def matches(self, code: str) -> bool:
        if self.factor.endswith("*"):
            return code.startswith(self.factor[:-1])
        return code == self.factor


def load_product_rules(path: Path = PRODUCTS_FILE) -> list[ProductRule]:
    with path.open("rb") as f:
        return [ProductRule(**rule) for rule in tomllib.load(f)["rule"]]


def _fmt_pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " %"


def _fmt_mln(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} млн ₽"


class Tools:
    def __init__(
        self,
        company: CompanyData,
        library: Library,
        recorder: TraceRecorder,
        product_rules: list[ProductRule] | None = None,
    ) -> None:
        self.company = company
        self.library = library
        self.trace = recorder
        self.rules = product_rules if product_rules is not None else load_product_rules()

    def _call(
        self,
        name: str,
        args: dict,
        fn: Callable,
        refs: Callable[[object], list[str]],
        summary: Callable,
        found: Callable[[object], list[str]] | None = None,
    ):
        if name in TOOL_STAGES:
            self.trace.stage(TOOL_STAGES[name])
        try:
            result = fn()
        except Exception as exc:  # инструмент упал — агент работает с тем, что есть, и пишет об этом
            # в трассе (она видна по API) — только тип ошибки, без текста: в нём бывают детали БД
            self.trace.tool(name, args, [], f"ошибка инструмента: {type(exc).__name__}")
            return None
        self.trace.tool(name, args, refs(result), summary(result))
        if found is not None and result is not None:
            try:
                self.trace.found(*found(result))
            except Exception:  # подпись находки не должна ронять инструмент
                pass
        return result

    # --- модуль профиля ----------------------------------------------------------------------------

    def exposure_map(self, ctx: AgentContext) -> None:
        cid = ctx.profile.id
        result = self._call(
            "get_exposure_map",
            {"company_id": cid},
            lambda: self.company.exposure_map(cid),
            lambda r: sorted({x for f in r for x in f.refs}),
            lambda r: (
                "факторы: "
                + (
                    ", ".join(f"{f.code}={f.level}" for f in r if LEVEL_RANK.get(f.level, 0) >= 1)
                    or "нет значимых"
                )
            ),
            lambda r: [
                f"Заметно зависит: {f.label}"
                for f in sorted(r, key=lambda f: -LEVEL_RANK.get(f.level, 0))
                if LEVEL_RANK.get(f.level, 0) >= 2
            ][:3],
        )
        ctx.exposure = result or []
        if result is None:
            ctx.warnings.append(
                "не удалось понять, от чего зависит бизнес компании, — вывод только по профилю"
            )

    def counterparty_chain(self, ctx: AgentContext) -> None:
        cid = ctx.profile.id
        result = self._call(
            "get_counterparty_chain",
            {"company_id": cid, "event_id": ctx.event.id},
            lambda: self.company.counterparty_chain(cid, ctx.event.source),
            lambda r: sorted(
                {x for ch in r.channels for x in ch.refs}
                | {c.id for ch in r.channels for c in ch.counterparties}
            ),
            lambda r: "; ".join(ch.text for ch in r.channels) or ("каналов нет: " + "; ".join(r.gaps)),
            lambda r: (
                [ch.text for ch in r.channels][:3]
                or [
                    "Оценить влияние через покупателей и поставщиков не удалось — данных мало"
                    if r.gaps
                    else "Через покупателей и поставщиков не доходит"
                ]
            ),
        )
        if result is not None:
            ctx.chain = result
            ctx.warnings += [g for g in result.gaps if g not in ctx.warnings]

    def group_impact(self, ctx: AgentContext) -> None:
        cid = ctx.profile.id
        result = self._call(
            "get_group_impact",
            {"company_id": cid, "event_id": ctx.event.id},
            lambda: self.company.group_impact(cid, ctx.event.source),
            lambda r: [] if r is None else [*r.refs, *(m.id for m in r.members)],
            lambda r: "группы нет" if r is None else r.text or f"задето {len(r.members)} из {r.size}",
            lambda r: [f"Касается {len(r.members)} компаний группы из {r.size}"] if r and r.members else [],
        )
        ctx.group = result

    # --- модуль поиска -----------------------------------------------------------------------------

    def search_alfa_analytics(
        self, ctx: AgentContext, query: str, factors: list[str] | None = None, material: str | None = None
    ) -> int:
        args = {"query": query, "factors": factors or []} | ({"material": material} if material else {})
        result = self._call(
            "search_alfa_analytics",
            args,
            lambda: self.library.search_alfa_analytics(query, factors=factors, limit=5, material=material),
            lambda r: [h.source.id for h in r],
            lambda r: f"найдено {len(r)}: " + ", ".join(sorted({h.page_ref for h in r})),
            lambda r: [_material_found(h) for h in r if not h.stale],
        )
        added = 0
        known = {h.source.id for h in ctx.analytics}
        for hit in result or []:
            if hit.stale or hit.source.id in known:
                continue
            ctx.analytics.append(hit)
            known.add(hit.source.id)
            added += 1
        return added

    def search_news(self, ctx: AgentContext, query: str, factors: list[str] | None = None) -> None:
        before = ctx.event.source.published_at
        result = self._call(
            "search_news",
            {"query": query, "factors": factors or []},
            lambda: self.library.search_news(query, factors=factors, before=before, limit=3),
            lambda r: [e.id for e in r],
            lambda r: f"найдено {len(r)}",
            lambda r: [f"Новость: {e.source.title[:110]}" for e in r if e.id != ctx.event.id][:2],
        )
        known = {ctx.event.id, *(e.id for e in ctx.news)}
        for e in result or []:
            if e.id not in known:
                ctx.news.append(e)
                known.add(e.id)

    def load_pages(self, ctx: AgentContext, refs: set[str]) -> None:
        """Тексты страниц материалов банка — для сверки цитат."""
        for ref in sorted(refs):
            if ref in ctx.page_texts:
                continue
            text = self._call(
                "alfa_page_text",
                {"ref": ref},
                lambda ref=ref: self.library.alfa_page_text(ref),
                lambda r, ref=ref: [ref] if r else [],
                lambda r: f"{len(r)} символов" if r else "страницы нет",
            )
            ctx.page_texts[ref] = text or ""

    # --- свои инструменты ----------------------------------------------------------------------------

    def products_for_risk(self, ctx: AgentContext) -> None:
        """Одно предложение продукта под самый сильный риск события — только при силе не ниже средней."""
        self.trace.stage(TOOL_STAGES["get_products_for_risk"])
        direct = {f.code for f in ctx.event.factors}
        event_codes = direct | {ch.factor for ch in ctx.chain.channels if ch.factor}
        # сначала факторы самого события, потом каналы цепочки; внутри — по силе риска у компании
        candidates = sorted(
            (f for f in ctx.exposure if f.code in event_codes and LEVEL_RANK.get(f.level, 0) >= 2),
            key=lambda f: (f.code not in direct, -LEVEL_RANK[f.level], -(f.strength or 0)),
        )
        features = {f.id: f.value for f in ctx.profile.features}
        offer = None
        for factor in candidates:
            for rule in self.rules:
                if not rule.matches(factor.code) or (rule.roles and ctx.persona.role not in rule.roles):
                    continue
                has = bool(rule.feature) and bool(features.get(rule.feature))
                template = rule.has_text if has else rule.new_text
                if not template:
                    continue
                channel = next((ch for ch in ctx.chain.channels if ch.factor == factor.code), None)
                sector = (channel.sector if channel else None) or factor.label
                share = (
                    _fmt_pct((channel.share or 0) * 100).replace(",0 %", " %")
                    if channel and channel.share
                    else ""
                )
                if "{share}" in template and not share:
                    continue
                refs = sorted(
                    {*factor.refs, *([rule.feature] if has else []), *(channel.refs if channel else [])}
                )
                offer = Offer(rule.product, template.format(sector=sector, share=share), refs, factor.code)
                break
            if offer:
                break
        ctx.offer = offer
        if offer:
            self.trace.found(offer.text)
        self.trace.tool(
            "get_products_for_risk",
            {"factors": [f.code for f in candidates]},
            offer.refs if offer else [],
            f"{offer.product}: {offer.text}" if offer else "нет риска не ниже средней с честным продуктом",
        )

    def estimate_rate_impact(self, ctx: AgentContext) -> None:
        """Расчёты в рублях только по честным формулам (фичи C + E), сценарий — прогноз банка со страницей.

        - кредит или лизинг: на каждый 1 млрд ₽ долга по плавающей ставке, Δ = долг × Δставки;
        - депозит: доход на 100 млн ₽ при ставке сейчас и по прогнозу банка на конец 2027 г.;
        - ВЭД и фактор курса в событии: на каждые 100 млн ₽ валютных расчётов изменение курса на 10 %.
        Объёмов долга, остатков и ВЭД в данных нет — считаем «на единицу», сумму вводит пользователь.
        """
        self.load_pages(ctx, set(BANK_RATE["pages"]))
        self.trace.stage(TOOL_STAGES["estimate_rate_impact"])  # после сверки страниц — она пишет свой этап
        verified = all(
            all(_number_on_page(n, ctx.page_texts.get(ref, "")) for n in numbers)
            for ref, numbers in BANK_RATE["pages"].items()
        )
        features = {f.id: f.value for f in ctx.profile.features}
        exposure = {f.code: f for f in ctx.exposure if LEVEL_RANK.get(f.level, 0) >= 1}
        event_codes = {f.code for f in ctx.event.factors}
        pages = sorted(BANK_RATE["pages"])
        out: list[Estimate] = []

        rate_relevant = event_codes & {"rate", "deposit_yield", "inflation"}
        if verified and rate_relevant:
            r = BANK_RATE
            if features.get("feat:CL_PRODUCT_LOA_MARK") or features.get("feat:CL_PRODUCT_LEA_MARK"):
                delta = r["end_2026"] - r["previous_end_2026"]
                refs = [
                    *pages,
                    *(x for x in ("feat:CL_PRODUCT_LOA_MARK", "feat:CL_PRODUCT_LEA_MARK") if features.get(x)),
                ]
                out.append(
                    Estimate(
                        "est:rate_debt",
                        Statement(
                            text=(
                                "На каждый 1 млрд ₽ долга по плавающей ставке: прогноз банка на конец 2026 "
                                "г. — "
                                f"{_fmt_pct(r['end_2026'])} вместо прежних "
                                f"{_fmt_pct(r['previous_end_2026'])}, это "
                                f"+{_fmt_mln(1000 * delta / 100)} процентов в год. Формула: долг × Δставки = "
                                f"1 млрд ₽ × {_fmt_pct(delta).replace(' %', ' п.п')}. Свой долг и тип "
                                "ставки в данных "
                                "банка не указаны — введите сумму, без неё расчёта нет."
                            ),
                            origin="estimate",
                            refs=refs,
                            confidence="medium",
                        ),
                        "risks",
                        "rate",
                    )
                )
            if features.get("feat:CL_PRODUCT_DEP_MARK") or "deposit_yield" in exposure:
                now_income, later_income = r["current"], r["end_2027"]
                refs = [
                    *pages,
                    *(["feat:CL_PRODUCT_DEP_MARK"] if features.get("feat:CL_PRODUCT_DEP_MARK") else []),
                ]
                out.append(
                    Estimate(
                        "est:deposit",
                        Statement(
                            text=(
                                "Каждые 100 млн ₽ под ставку, следующую за ключевой (допущение сервиса): "
                                "при "
                                f"{_fmt_pct(now_income)} — около {_fmt_mln(now_income)} в год, при "
                                f"{_fmt_pct(later_income)} (прогноз банка на конец 2027 г.) — около "
                                f"{_fmt_mln(later_income)}; разница {_fmt_mln(now_income - later_income)} в "
                                "год. "
                                "Остатков компании в данных нет — сумму вводит пользователь."
                            ),
                            origin="estimate",
                            refs=refs,
                            confidence="medium",
                        ),
                        "opportunities",
                        "deposit_yield",
                    )
                )
        if "fx" in event_codes and features.get("feat:FTS_FLAG"):
            out.append(
                Estimate(
                    "est:fx",
                    Statement(
                        text=(
                            "На каждые 100 млн ₽ валютных расчётов изменение курса на 10 % — это ±10 млн ₽ "
                            "в рублёвом "
                            "выражении. Направление ВЭД (импорт или экспорт) и объём в данных банка не "
                            "указаны — "
                            "знак и сумму определяет пользователь."
                        ),
                        origin="estimate",
                        refs=[
                            "feat:FTS_FLAG",
                            *(["feat:FTS_COUNTRY_NAME"] if features.get("feat:FTS_COUNTRY_NAME") else []),
                        ],
                        confidence="medium",
                    ),
                    "factors",
                    "fx",
                )
            )
        ctx.estimates = out
        self.trace.found(*(_short(e.statement.text) for e in out))
        if rate_relevant and not verified:
            ctx.warnings.append(
                "расчёт в рублях не показан: прогноз банка по ставке не удалось сверить с материалом"
            )
        self.trace.tool(
            "estimate_rate_impact",
            {"event_factors": sorted(event_codes), "bank_forecast_verified": verified},
            sorted({r for e in out for r in e.statement.refs}),
            "; ".join(e.id for e in out) or "честной формулы для события нет — расчёта нет",
        )


def _short(text: str, limit: int = 150) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _material_found(hit: AnalyticsHit) -> str:
    date = f" от {hit.material_date:%d.%m.%Y}" if hit.material_date else ""
    return f"Материал банка «{hit.source.title[:90]}»{date}"


def _number_on_page(number: str, text: str) -> bool:
    compact = text.replace(" ", "")
    return number.replace(" ", "") in compact


def hits_by_page(hits: list[AnalyticsHit]) -> set[str]:
    return {h.page_ref for h in hits}


def event_factor_codes(event: Event) -> list[str]:
    return [f.code for f in sorted(event.factors, key=lambda f: -f.strength)]
