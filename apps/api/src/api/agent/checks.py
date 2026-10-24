"""Самопроверка черновика — детерминированная, без модели: правила «Агента интерпретации» из спецификации.

- у fact, bank и data есть refs, и все refs ведут на источник или признак из контекста;
- факт есть в тексте источника: дословная выдержка найдена, цифры утверждения есть в источнике;
- цитата банка есть в распознанном тексте страницы, материал не устаревший;
- учтено не меньше двух факторов или каналов компании;
- роль отражена в «почему важно» и в действиях;
- числа только из данных и источников, суммы в рублях модель сама не пишет (их дают расчётные инструменты);
- нет утверждений про контрагентов, которых нет в цепочке или группе.

Проблема конкретного утверждения — «жёсткая»: если доработка её не исправит, утверждение убирается из
карточки. Проблемы карточки целиком (факторы, роль, пересказ) — повод переписать; не исправлены —
предупреждение.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from api.agent.context import ROLE_STEMS, AgentContext
from api.agent.drafts import Draft, DraftStatement
from api.agent.forecasts import superseded
from api.agent.numbers import NumberBank, money_in

CHECKS = (
    "refs",
    "facts_in_source",
    "bank_quotes",
    "numbers_from_tools",
    "counterparties_in_chain",
    "fresh_forecast",
    "multi_factor",
    "role",
    "not_retelling",
)

QUOTE_MIN, QUOTE_MAX = 10, 300

# какое происхождение допустимо в блоке карточки: позиция банка — отдельно, последствия — выводы модели
BLOCK_ORIGINS = {
    "what_happened": {"fact"},
    "why_it_matters": {"data", "ai", "fact"},
    "risks": {"ai"},
    "opportunities": {"ai"},
    "watch": {"ai", "fact", "data"},
    "bank_view": {"bank"},
}
BLOCK_RULES = {
    "what_happened": "в «что произошло» только факты (fact)",
    "why_it_matters": "в «почему важно» — данные о компании (data) и выводы (ai); позиция банка — только в "
    "bank_view",
    "risks": "риски — это выводы (ai); данные и факты — в «почему важно», позиция банка — в bank_view",
    "opportunities": "возможности — это выводы (ai); данные и факты — в «почему важно», позиция банка — в "
    "bank_view",
    "watch": "позиция банка — только в bank_view",
    "bank_view": "в позиции банка только origin=bank",
}

_QUOTES = str.maketrans(
    {"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "ё": "е", "Ё": "Е"}
)
_DASHES = re.compile(r"[‐-―−]")
_SPACE = re.compile(r"\s+")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_INFERENCE = re.compile(
    r"\b(?:поэтому|следовательно|значит|что означает|то есть|а значит|из-за чего|что делает|это означает)\b",
    re.IGNORECASE,
)
_COMPANY_REF = re.compile(r"\bU_\d+\b")
_COMPANY_NO = re.compile(r"Компани[яиюей]\s*№\s*(\d+)")


def normalize(text: str) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text or "")
    text = _DASHES.sub("-", text.translate(_QUOTES))
    text = text.replace("­", "")
    return _SPACE.sub(" ", text).strip().lower()


_STEM_WORD = re.compile(r"[а-яёa-z]{4,}|\d+(?:[.,]\d+)?", re.IGNORECASE)
_GENERIC = {"альфа", "банк", "банка", "банке", "компа", "котор", "также", "этого", "может"}


def _stems(text: str) -> set[str]:
    return {w.lower().replace("ё", "е")[:5].replace(",", ".") for w in _STEM_WORD.findall(text)} - _GENERIC


# дата материала — «от 11.09.2026»; даты событий («заседание 23.10.2026») не проверяем
_DATE = re.compile(r"\bот\s+(\d{2}\.\d{2}\.\d{4})\b")


def _parse_date(text: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return None


def related(text: str, quote: str) -> bool:
    """Выдержка относится к утверждению: хотя бы два общих слова (по основе) или числа."""
    return len(_stems(text) & _stems(quote)) >= 2


def quote_in(quote: str, text: str) -> bool:
    q = normalize(quote).strip(" .,;:\"'…")
    return len(q) >= QUOTE_MIN and q in normalize(text)


@dataclass
class Issue:
    check: str
    message: str
    block: str | None = None
    index: int | None = None
    hard: bool = False

    def where(self) -> str:
        return f"{self.block}[{self.index}]" if self.block is not None else "карточка"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def passed(self) -> list[str]:
        failed = {i.check for i in self.issues}
        return [c for c in CHECKS if c not in failed]

    def hard_at(self) -> set[tuple[str, int]]:
        return {(i.block, i.index) for i in self.issues if i.hard and i.block is not None}

    def summary(self) -> str:
        if self.ok:
            return "все проверки пройдены"
        return "; ".join(f"{i.where()}: {i.message}" for i in self.issues[:12])


class Checker:
    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self.sources = ctx.sources()
        self.features = ctx.feature_ids()
        self.company_numbers = ctx.company_numbers()
        self.all_numbers = ctx.all_numbers()
        self.counterparties = ctx.counterparty_ids()

    # --- ссылки ---------------------------------------------------------------------------------

    def resolves(self, ref: str) -> bool:
        if ref.startswith("feat:"):
            return ref in self.features
        if ref in self.sources or ref.split("#", 1)[0] in self.sources:
            return True
        return self.ctx.page_ref_of(ref) is not None

    def source_text(self, ref: str) -> str:
        """Текст, в котором должен найтись факт: новость целиком или распознанная страница материала банка."""
        page = self.ctx.page_ref_of(ref)
        if page is not None:
            return self.ctx.page_texts.get(page, "")
        src = self.sources.get(ref) or self.sources.get(ref.split("#", 1)[0])
        if src is None:
            return ""
        if src.id == self.ctx.event.id:
            return self.ctx.event.text
        return f"{src.title}\n{src.fragment or ''}"

    # --- одно утверждение ------------------------------------------------------------------------

    def statement(self, block: str, i: int, s: DraftStatement) -> list[Issue]:
        out: list[Issue] = []

        def bad(check: str, message: str, hard: bool = True) -> None:
            out.append(Issue(check, message, block, i, hard))

        src_refs = [r for r in s.refs if r.startswith("src:")]
        feat_refs = [r for r in s.refs if r.startswith("feat:")]
        unresolved = [r for r in s.refs if not self.resolves(r)]
        if unresolved:
            bad("refs", f"ссылки не из контекста: {', '.join(unresolved[:4])}")
        if s.origin == "fact" and not src_refs:
            bad("refs", "факт без источника (нужен src:…)")
        if s.origin == "bank" and not any(self.ctx.page_ref_of(r) for r in src_refs):
            bad("refs", "позиция банка без ссылки на страницу аналитики Альфа-Банка")
        if s.origin == "data" and not feat_refs:
            bad("refs", "данные о компании без признака (нужен feat:…)")

        if s.origin in ("fact", "bank"):
            # цитата банка сверяется только со страницами аналитики, не с новостью из тех же refs
            cited_refs = [r for r in src_refs if self.resolves(r)]
            if s.origin == "bank":
                cited_refs = [r for r in cited_refs if self.ctx.page_ref_of(r)]
            texts = [self.source_text(r) for r in cited_refs]
            check = "facts_in_source" if s.origin == "fact" else "bank_quotes"
            if not s.quote:
                bad(check, "нет дословной выдержки из источника (quote)")
            elif len(s.quote) > QUOTE_MAX:
                bad(check, f"выдержка длиннее {QUOTE_MAX} символов — нужен короткий фрагмент")
            elif not any(quote_in(s.quote, t) for t in texts):
                what = "в тексте источника" if s.origin == "fact" else "в распознанном тексте страницы"
                bad(check, f"выдержка не найдена {what}: «{s.quote[:80]}»")
            elif not related(s.text, s.quote):
                bad(check, "выдержка не подтверждает утверждение: у текста и выдержки нет общих слов и чисел")
            if s.origin == "bank":
                stale = [h.source.id for h in self.ctx.analytics if h.stale and h.source.id in s.refs]
                if stale:
                    bad("bank_quotes", "ссылка на устаревший материал — это не позиция банка")
                # дата материала в тексте — одного из процитированных материалов, а не придуманная
                dates = {
                    h.material_date
                    for h in self.ctx.analytics
                    if h.material_date and (h.source.id in s.refs or h.page_ref in s.refs)
                }
                wrong = [d for d in _DATE.findall(s.text) if dates and _parse_date(d) not in dates]
                if wrong:
                    known = ", ".join(sorted(d.strftime("%d.%m.%Y") for d in dates))
                    bad("bank_quotes", f"дата материала {wrong[0]} не совпадает с процитированным ({known})")
            cited = NumberBank()
            for t in texts:
                cited.add_text(t)
            missing = cited.unsupported(s.text)
            if missing:
                bad(check, f"чисел нет в источнике: {', '.join(missing[:4])}")
        elif s.origin == "data":
            if _INFERENCE.search(s.text):
                bad("not_retelling", "в данных о компании — вывод («поэтому…»): вывод вынеси отдельным ai")
            missing = self.company_numbers.unsupported(s.text)
            if missing:
                bad("numbers_from_tools", f"чисел нет в данных о компании: {', '.join(missing[:4])}")
        elif s.origin == "ai":
            money = money_in(s.text)
            if money:
                bad("numbers_from_tools", f"суммы в рублях пишет только расчётный инструмент: {money[0]}")
            missing = self.all_numbers.unsupported(s.text)
            if missing:
                bad("numbers_from_tools", f"чисел нет ни в данных, ни в источниках: {', '.join(missing[:4])}")

        if s.origin in ("bank", "ai"):
            for hit in self.ctx.analytics:
                if hit.source.id in s.refs or hit.page_ref in s.refs:
                    newer = superseded(s.text, hit.source.id.split("#", 1)[0], hit.material_date)
                    if newer:
                        bad(
                            "fresh_forecast",
                            f"прогноз из материала от {hit.material_date:%d.%m.%Y} банк пересмотрел "
                            f"{newer.date:%d.%m.%Y} ({newer.material}): возьми актуальный или напиши "
                            f"«раньше банк ждал…»",
                        )
                        break
        unknown = self.unknown_companies(s.text, s.refs)
        if unknown:
            bad("counterparties_in_chain", f"контрагентов нет в цепочке и группе: {', '.join(unknown[:3])}")
        return out

    def unknown_companies(self, text: str, refs: list[str]) -> list[str]:
        mentioned = set(_COMPANY_REF.findall(text)) | {f"U_{n}" for n in _COMPANY_NO.findall(text)}
        mentioned |= {r for r in refs if _COMPANY_REF.fullmatch(r)}
        return sorted(m for m in mentioned if m not in self.counterparties)

    # --- карточка целиком ------------------------------------------------------------------------

    def covered_factors(self, draft: Draft) -> set[str]:
        known = self.ctx.factor_codes()
        by_ref = self.ctx.ref_factors()
        covered: set[str] = set()
        for s in [*draft.why_it_matters, *draft.risks, *draft.opportunities]:
            if s.factor and s.factor in known:
                covered.add(s.factor)
            for r in s.refs:
                covered |= by_ref.get(r, set()) & known
        # канал и фактор одного смысла («через покупателей» = demand_56) считаем одним
        kinds = {"direct", "buyers", "suppliers", "group"}
        factors = {c for c in covered if c not in kinds}
        channels_only = {
            ch.kind
            for ch in self.ctx.chain.channels
            if ch.kind in covered and not (ch.factor and ch.factor in factors)
        }
        return factors | channels_only

    def run(self, draft: Draft) -> Report:
        report = Report()
        for block, i, s in draft.statements():
            report.issues += self.statement(block, i, s)
            allowed = BLOCK_ORIGINS[block]
            if s.origin not in allowed:
                report.issues.append(Issue("not_retelling", BLOCK_RULES[block], block, i, True))
        for i, a in enumerate(draft.actions):
            unresolved = [r for r in a.refs if not self.resolves(r)]
            if unresolved:
                report.issues.append(
                    Issue("refs", f"ссылки не из контекста: {', '.join(unresolved[:4])}", "actions", i, True)
                )
            # в сценарии числа — допущения («снижение на 5 %»), в вопросе — должны быть из данных
            missing = self.all_numbers.unsupported(a.text) if a.kind == "question" else []
            if missing:
                report.issues.append(
                    Issue(
                        "numbers_from_tools",
                        f"чисел нет в данных: {', '.join(missing[:4])}",
                        "actions",
                        i,
                        True,
                    )
                )
            unknown = self.unknown_companies(a.text, a.refs)
            if unknown:
                report.issues.append(
                    Issue(
                        "counterparties_in_chain",
                        f"контрагентов нет в цепочке: {', '.join(unknown)}",
                        "actions",
                        i,
                        True,
                    )
                )
            money = money_in(a.text)
            if money:
                report.issues.append(
                    Issue("numbers_from_tools", f"суммы в рублях в действии: {money[0]}", "actions", i, True)
                )

        covered = self.covered_factors(draft)
        available = self.ctx.factor_codes()
        if len(covered) < 2:
            if len(available) < 2:
                report.warnings.append("в данных компании меньше двух факторов, связанных с событием")
            report.issues.append(
                Issue(
                    "multi_factor",
                    f"учтён {len(covered)} фактор(ов) компании ({', '.join(sorted(covered)) or 'нет'}); "
                    f"нужно ≥ 2"
                    f" из: {', '.join(sorted(available)) or 'нет'} — иначе это пересказ",
                )
            )

        stems = ROLE_STEMS.get(self.ctx.persona.role, ())
        if stems:
            why = " ".join(s.text for s in draft.why_it_matters).lower()
            acts = " ".join(a.text for a in draft.actions).lower()
            missing = [
                name
                for name, text in (("почему важно", why), ("действия", acts))
                if not any(x in text for x in stems)
            ]
            if missing:
                report.issues.append(
                    Issue(
                        "role",
                        f"роль «{self.ctx.persona.role_label}» не отражена: {', '.join(missing)}",
                    )
                )

        if not draft.what_happened:
            report.issues.append(Issue("not_retelling", "нет фактов события"))
        if not any(s.origin == "data" for s in draft.why_it_matters):
            report.issues.append(
                Issue("not_retelling", "в «почему важно» нет данных о компании (origin=data)")
            )
        if not any(s.origin == "ai" for s in draft.why_it_matters):
            report.issues.append(
                Issue("not_retelling", "в «почему важно» нет вывода для компании (origin=ai)")
            )
        if not draft.risks and not draft.opportunities:
            report.issues.append(Issue("not_retelling", "нет ни рисков, ни возможностей — это пересказ"))
        if not draft.actions:
            report.issues.append(Issue("role", "нет действий"))

        usable = [h for h in self.ctx.analytics if not h.stale]
        if usable and not draft.bank_view:
            report.issues.append(
                Issue("bank_quotes", "в контексте есть аналитика банка, а позиции банка в карточке нет")
            )
        return report
