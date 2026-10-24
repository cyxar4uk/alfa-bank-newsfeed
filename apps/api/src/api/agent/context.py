"""Единый контекст компании и события: всё, что агент собрал инструментами, и как это показать модели.

Текст новостей и аналитики попадает к модели только внутри разделителей `<<<ДАННЫЕ …>>> … <<<КОНЕЦ ДАННЫХ>>>`:
это материал для анализа, а не инструкции. Сами разделители из текста вычищаются, чтобы источник не мог
«закрыть» блок данных и дописать свои указания.
"""

import datetime as dt
import json
import re
from dataclasses import dataclass, field

from api.agent.numbers import NumberBank
from api.agent.ports import LEVEL_RANK, AnalyticsHit, Chain, Event, ExposureFactor, GroupImpact
from api.contract import CompanyProfile, Persona, Source, Statement

DATA_OPEN = "<<<ДАННЫЕ"
DATA_CLOSE = "<<<КОНЕЦ ДАННЫХ>>>"
_DELIMS = re.compile(r"<{2,}|>{2,}")

# акценты ролей (03_features.md, фича D) — в промпт и в самопроверку
ROLE_FOCUS: dict[str, str] = {
    "owner": "стоимость бизнеса, группа компаний, стратегия отрасли",
    "ceo": "спрос, поставщики, конкуренты, операционная деятельность",
    "cfo": "долг, ставка, ликвидность, ковенанты, валюта",
    "chief_accountant": "налоги, отчётность, регулирование, сроки, курсовые разницы",
    "treasury": "курс, остатки, депозиты, платёжные риски ВЭД",
    "other": "общее влияние на бизнес",
}
# основы слов, по которым видно, что текст написан для роли
ROLE_STEMS: dict[str, tuple[str, ...]] = {
    "owner": (
        "стоимост",
        "групп",
        "стратег",
        "капитал",
        "акционер",
        "дивиденд",
        "инвест",
        "актив",
        "холдинг",
    ),
    "ceo": (
        "спрос",
        "поставщик",
        "покупател",
        "конкурент",
        "операц",
        "закуп",
        "продаж",
        "клиент",
        "цен",
        "выручк",
    ),
    "cfo": (
        "долг",
        "ставк",
        "ликвидн",
        "ковенант",
        "валют",
        "кредит",
        "процент",
        "финансир",
        "бюджет",
        "курс",
    ),
    "chief_accountant": (
        "налог",
        "отчётн",
        "отчетн",
        "учёт",
        "учет",
        "резерв",
        "курсов",
        "разниц",
        "ндс",
        "взнос",
        "регулир",
        "срок",
        "фот",
        "расход",
        "контрол",
    ),
    "treasury": ("курс", "остат", "депозит", "ликвидн", "платеж", "платёж", "размещ", "валют", "доходн"),
    "other": (),
}


def clean(text: str | None) -> str:
    """Текст из источника без разделителей блока данных — источник не может закрыть блок сам."""
    return _DELIMS.sub(" ", text or "").strip()


def as_data(source_id: str, text: str | None, meta: str = "") -> str:
    meta = " ".join(clean(meta).split())
    head = f"{DATA_OPEN} {clean(source_id)}{(' · ' + meta) if meta else ''}>>>"
    body = clean(text)
    return f"{head}\n{body}\n{DATA_CLOSE}"


_COMPANY_ID = re.compile(r"\bU_(\d+)\b")


def _named(text: str) -> str:
    """«U_153112» → «Компания №153112»: модель пишет то, что видит, а служебные id пользователю не нужны.

    Самопроверка понимает оба написания («Компания №N» сопоставляется с U_N), refs на id не нужны.
    """
    return _COMPANY_ID.sub(r"Компания №\1", text)


def _short(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.0f} %"


@dataclass
class Estimate:
    """Готовый расчёт инструмента: утверждение `estimate` и куда его положить."""

    id: str
    statement: Statement
    place: str  # risks | opportunities | factors
    factor: str


@dataclass
class Offer:
    product: str
    text: str
    refs: list[str]
    factor: str


@dataclass
class AgentContext:
    persona: Persona
    profile: CompanyProfile
    event: Event
    exposure: list[ExposureFactor] = field(default_factory=list)
    chain: Chain = field(default_factory=Chain)
    group: GroupImpact | None = None
    analytics: list[AnalyticsHit] = field(default_factory=list)
    news: list[Event] = field(default_factory=list)
    estimates: list[Estimate] = field(default_factory=list)
    offer: Offer | None = None
    page_texts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # --- что можно цитировать и на что ссылаться ------------------------------------------------

    def sources(self) -> dict[str, Source]:
        out = {self.event.id: self.event.source}
        for e in self.news:
            out.setdefault(e.id, e.source)
        for hit in self.analytics:
            out.setdefault(hit.source.id, hit.source)
        return out

    def page_ref_of(self, ref: str) -> str | None:
        """Страница материала банка для ссылки на фрагмент или на саму страницу."""
        for hit in self.analytics:
            if ref in (hit.source.id, hit.page_ref):
                return hit.page_ref
        return None

    def feature_ids(self) -> set[str]:
        ids = {f.id for f in self.profile.features}
        for f in self.exposure:
            ids.update(r for r in f.refs if r.startswith("feat:"))
        for ch in self.chain.channels:
            ids.update(r for r in ch.refs if r.startswith("feat:"))
        if self.group:
            ids.update(r for r in self.group.refs if r.startswith("feat:"))
        return ids

    def factor_codes(self) -> set[str]:
        """Факторы и каналы компании, которые реально есть в данных (сила не ниже низкой)."""
        codes = {f.code for f in self.exposure if LEVEL_RANK.get(f.level, 0) >= 1}
        for ch in self.chain.channels:
            codes.add(ch.kind)
            if ch.factor:
                codes.add(ch.factor)
        if self.group and self.group.members:
            codes.add("group")
        return codes

    def counterparty_ids(self) -> set[str]:
        ids = {self.profile.id}
        # крупнейшие контрагенты из профиля (в признаках компании) — называть их можно
        ids.update(c.id for c in self.profile.counterparties)
        for ch in self.chain.channels:
            ids.update(c.id for c in ch.counterparties)
        if self.group:
            ids.update(m.id for m in self.group.members)
        return ids

    def ref_factors(self) -> dict[str, set[str]]:
        """Признак → факторы и каналы, доказательством которых он служит."""
        out: dict[str, set[str]] = {}
        for f in self.exposure:
            if LEVEL_RANK.get(f.level, 0) >= 1:
                for r in f.refs:
                    out.setdefault(r, set()).add(f.code)
        for ch in self.chain.channels:
            for r in ch.refs:
                out.setdefault(r, set()).update({ch.kind, *([ch.factor] if ch.factor else [])})
        return out

    def company_numbers(self) -> NumberBank:
        bank = NumberBank()
        for f in self.profile.features:
            bank.add_value(f.value)
            bank.add_text(f.display)
        for c in self.profile.counterparties:
            bank.add_value([c.amount, c.share])
        p = self.profile.payments
        if p:
            bank.add_value([p.turnover, p.intra_group_amount, p.intra_group_share, p.revenue_coverage or 0])
            for side in (p.customers, p.suppliers):
                bank.add_value([side.amount, side.coverage, side.counterparties])
                for s in side.sectors:
                    bank.add_value([s.amount, s.share, s.counterparties])
                    bank.add_text(s.okved)
        if self.profile.group:
            bank.add_value(self.profile.group.size)
        if self.profile.industry:
            i = self.profile.industry
            bank.add_value([i.rank, i.total, i.class_rank, i.class_total, i.percentile])
        for f in self.exposure:
            bank.add_text(f.channel_text)
            bank.add_value([f.strength or 0, f.coverage or 0])
        for ch in self.chain.channels:
            bank.add_text(ch.text)
            bank.add_text(ch.okved)
            bank.add_value([ch.share or 0, ch.coverage or 0])
            for c in ch.counterparties:
                bank.add_value(c.share or 0)
        if self.group:
            bank.add_text(self.group.text)
            bank.add_value([self.group.size, self.group.revenue_total or 0, len(self.group.members)])
            for m in self.group.members:
                bank.add_value(m.revenue or 0)
        return bank

    def all_numbers(self) -> NumberBank:
        bank = self.company_numbers()
        bank.add_text(self.event.text)
        for src in self.sources().values():
            bank.add_text(src.title)
            bank.add_text(src.fragment)
        for text in self.page_texts.values():
            bank.add_text(text)
        return bank

    # --- как показать модели --------------------------------------------------------------------

    def render_company(self) -> str:
        p = self.profile
        lines = [
            f"Компания: {p.display_name}",
            f"Пользователь: {self.persona.role_label} — акценты роли: "
            f"{ROLE_FOCUS.get(self.persona.role, '')}",
            "Признаки компании (id · название · значение):",
        ]
        for f in p.features:
            value = f.display if f.display is not None else f.value
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            lines.append(f"- {f.id} · {f.label} · {_named(str(value))}")
        if p.missing:
            lines.append("Нет в данных: " + "; ".join(f"{m.label} ({m.reason})" for m in p.missing))
        if p.data_notes:
            lines.append("Замечания к данным: " + "; ".join(p.data_notes))
        return "\n".join(lines)

    def render_exposure(self) -> str:
        if not self.exposure:
            return "Карта чувствительности: нет данных."
        lines = ["Карта чувствительности (код · фактор · сила · канал · доказательства):"]
        for f in sorted(self.exposure, key=lambda f: -LEVEL_RANK.get(f.level, 0)):
            cov = f" · покрытие {_short(f.coverage)}" if f.coverage is not None else ""
            lines.append(f"- {f.code} · {f.label} · {f.level} · {f.channel_text}{cov} · {', '.join(f.refs)}")
        return "\n".join(lines)

    def render_chain(self) -> str:
        lines = ["Через кого событие доходит до компании (цепочка по платежам):"]
        if not self.chain.channels:
            lines.append("- каналов через контрагентов нет")
        for ch in self.chain.channels:
            cps = "; ".join(
                c.display_name
                + (f" {_short(c.share)}" if c.share is not None else "")
                + (" (группа)" if c.intra_group else "")
                for c in ch.counterparties[:5]
            )
            lines.append(
                f"- {ch.kind}{(' · ' + ch.factor) if ch.factor else ''} · {ch.text} · {', '.join(ch.refs)}"
            )
            if cps:
                lines.append(f"  контрагенты: {cps}")
        for gap in self.chain.gaps:
            lines.append(f"- пробел: {gap}")
        return "\n".join(lines)

    def render_group(self) -> str:
        if not self.group:
            return "Группа компаний: нет или не нужна для этого события."
        g = self.group
        lines = [f"Группа {g.group_id}: {g.size} компаний. {g.text} · {', '.join(g.refs)}"]
        for m in g.members[:10]:
            rev = f", выручка {m.revenue / 1e9:.1f} млрд ₽" if m.revenue else ""
            lines.append(f"- {m.display_name}{rev} · факторы: {', '.join(m.factors)}")
        return "\n".join(lines)

    def render_event(self) -> str:
        s = self.event.source
        meta = " · ".join(
            x for x in (s.publisher, s.published_at.date().isoformat() if s.published_at else None) if x
        )
        tags = ", ".join(f"{clean(f.code)} ({f.strength:.1f})" for f in self.event.factors) or "нет"
        sectors = ", ".join(f"{clean(t.okved)} {clean(t.name)}" for t in self.event.sectors) or "нет"
        parts = [
            "Событие (новость):",
            as_data(s.id, self.event.text, meta),
            f"Разметка парсера: факторы — {tags}; отрасли ОКВЭД — {sectors}",
        ]
        if self.event.expectations:
            parts.append("Ожидания рынка из текста новости:")
            for e in self.event.expectations:
                parts.append(as_data(s.id, f"{e.who}: {e.quote}", "ожидание"))
        return "\n".join(parts)

    def render_news(self) -> str:
        if not self.news:
            return "Другие новости по теме: не найдены."
        parts = ["Другие новости по теме:"]
        for e in self.news:
            s = e.source
            date = s.published_at.date().isoformat() if s.published_at else ""
            parts.append(
                as_data(s.id, f"{s.title}\n{s.fragment or ''}".strip(), f"{s.publisher or ''} {date}")
            )
        return "\n".join(parts)

    def render_analytics(self) -> str:
        if not self.analytics:
            return (
                "Аналитика Альфа-Банка по теме: не найдена — позиции банка по теме нет, bank_view оставь "
                "пустым."
            )
        parts = ["Аналитика Альфа-Банка (самый свежий материал важнее; указывай дату материала):"]
        for hit in sorted(self.analytics, key=lambda h: h.material_date or dt.date.min, reverse=True):
            s = hit.source
            date = hit.material_date.strftime("%d.%m.%Y") if hit.material_date else "дата неизвестна"
            parts.append(as_data(s.id, s.fragment, f"«{s.title}», {date}, стр. {s.page}"))
        return "\n".join(parts)

    def render_tools_extra(self) -> str:
        lines = []
        if self.estimates:
            lines.append(
                "Расчёты в рублях уже сделаны инструментом и будут добавлены в карточку сами — не пиши "
                "суммы в"
                " рублях и не пересказывай расчёт:"
            )
            lines += [f"- {e.statement.text}" for e in self.estimates]
        if self.offer:
            lines.append(
                "Предложение продукта банка добавит инструмент отдельным блоком — не упоминай продукты "
                "банка в"
                " анализе и действиях."
            )
        return "\n".join(lines)

    def render(self) -> str:
        blocks = [
            self.render_company(),
            self.render_exposure(),
            self.render_chain(),
            self.render_group(),
            self.render_event(),
            self.render_news(),
            self.render_analytics(),
            self.render_tools_extra(),
        ]
        return "\n\n".join(b for b in blocks if b)

    def snapshot(self) -> dict:
        """Контекст для уточняющих вопросов: сохраняется вместе с инсайтом."""
        return {
            "persona": self.persona.model_dump(mode="json"),
            "profile": self.profile.model_dump(mode="json"),
            "exposure": [f.model_dump(mode="json") for f in self.exposure],
            "chain": self.chain.model_dump(mode="json"),
            "group": self.group.model_dump(mode="json") if self.group else None,
            "analytics": [h.model_dump(mode="json") for h in self.analytics],
            "news": [e.model_dump(mode="json") for e in self.news],
            "event": self.event.model_dump(mode="json"),
            "page_texts": self.page_texts,
        }


def from_snapshot(snapshot: dict) -> AgentContext:
    return AgentContext(
        persona=Persona.model_validate(snapshot["persona"]),
        profile=CompanyProfile.model_validate(snapshot["profile"]),
        event=Event.model_validate(snapshot["event"]),
        exposure=[ExposureFactor.model_validate(f) for f in snapshot.get("exposure", [])],
        chain=Chain.model_validate(snapshot.get("chain") or {}),
        group=GroupImpact.model_validate(snapshot["group"]) if snapshot.get("group") else None,
        analytics=[AnalyticsHit.model_validate(h) for h in snapshot.get("analytics", [])],
        news=[Event.model_validate(e) for e in snapshot.get("news", [])],
        page_texts=dict(snapshot.get("page_texts", {})),
    )


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
