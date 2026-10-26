"""Проверка каждого утверждения карточки перед показом: на что оно опирается и сходятся ли числа.

Жюри и пользователь видят не «модель так сказала», а опору каждого предложения вывода: фрагмент новости,
материала Альфа-Банка или поле данных компании (критерии 2, 3, 11).

- Числа — детерминированно: каждое число текста должно найтись в фактах (новость, материалы банка, данные
  компании, расчёты сервиса), с нормализацией: 14 % = 14,0 %, 149 млрд = 149,0 млрд.
- Опора — по ссылкам утверждения, а у утверждений без ссылок (итог, шаги) — по совпадению слов с источниками,
  без модели: бесплатно и мгновенно.
- verified — опора есть и числа сходятся; partly — опора слабая или число не нашлось; hypothesis —
  предположение («Возможно, …»). Утверждение вывода с ненайденным числом и без опоры из карточки убирается.
"""

import re

from api.agent.checks import _stems
from api.agent.context import AgentContext
from api.agent.numbers import numbers_in
from api.contract import Claim, ClaimsSummary, ClaimSupport, Insight, Statement

MIN_OVERLAP = 2  # общих основ слов, чтобы фрагмент считался опорой утверждения без ссылок
QUOTE_MAX = 220
MAX_SUPPORT = 4
_SENTENCES = re.compile(r"(?<=[.!?…])\s+|\n+")
_POSSIBLE = re.compile(r"^(возможно|вероятно)\b", re.IGNORECASE)  # «можно обсудить…» — совет, не гипотеза


_split_cache: dict[int, list[tuple[str, set[str]]]] = {}


def _sentences(text: str) -> list[str]:
    return [s for s, _ in _split(text)]


def _split(text: str) -> list[tuple[str, set[str]]]:
    """Предложения источника с основами слов — один раз на текст (страница банка — десятки килобайт)."""
    key = hash(text or "")
    if key not in _split_cache:
        if len(_split_cache) > 256:
            _split_cache.clear()
        parts = [s.strip() for s in _SENTENCES.split(text or "") if len(s.strip()) >= 12]
        _split_cache[key] = [(s, _stems(s)) for s in parts]
    return _split_cache[key]


def _best_quote(claim: str, text: str) -> tuple[str, int]:
    """Предложение источника, больше всего общего с утверждением: (цитата, сколько общих основ)."""
    want = _stems(claim)
    best, score = "", 0
    for sentence, stems in _split(text):
        overlap = len(want & stems)
        if overlap > score:
            best, score = sentence, overlap
    return best[:QUOTE_MAX], score


def _shown(value) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


class Verifier:
    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self.numbers = ctx.all_numbers()
        for e in ctx.estimates:  # расчёт сервиса — тоже факт: его числа можно повторять в итоге
            self.numbers.add_text(e.statement.text)
        self.features = {f.id: f for f in ctx.profile.features}
        self.sources = ctx.sources()

    # --- опора по ссылке -----------------------------------------------------------------------------

    def _text_of(self, ref: str) -> tuple[str, str] | None:
        """(вид опоры, текст) для ссылки: новость, материал банка или признак компании."""
        if ref.startswith("feat:"):
            f = self.features.get(ref)
            if f is None:
                return None
            return "company", f"{f.label}: {_shown(f.display if f.display is not None else f.value)}"
        page = self.ctx.page_ref_of(ref)
        if page is not None:
            # фрагмент — сам фрагмент; страница целиком — только если ссылка на страницу
            return "bank", self._fragment(ref) or self.ctx.page_texts.get(page, "")
        src = self.sources.get(ref) or self.sources.get(ref.split("#", 1)[0])
        if src is None:
            return None
        if src.id == self.ctx.event.id:
            return "news", self.ctx.event.text
        if src.kind == "alfa_analytics":
            return "bank", src.fragment or src.title
        return "news", f"{src.title}. {src.fragment or ''}"

    def _fragment(self, ref: str) -> str:
        hit = next((h for h in self.ctx.analytics if ref in (h.source.id, h.page_ref)), None)
        return (hit.source.fragment or "") if hit else ""

    def support_for(self, text: str, refs: list[str]) -> list[ClaimSupport]:
        out: list[ClaimSupport] = []
        for ref in dict.fromkeys(refs):
            found = self._text_of(ref)
            if found is None:
                continue
            kind, source_text = found
            if kind == "company":
                out.append(ClaimSupport(kind=kind, ref=ref, quote=source_text[:QUOTE_MAX]))
                continue
            # ссылка — опора, только если источник говорит о том же: общие слова или то же число
            quote, score = _best_quote(text, source_text)
            if score >= MIN_OVERLAP:
                out.append(ClaimSupport(kind=kind, ref=ref, quote=quote))
        if not out:
            out = self.support_by_overlap(text)
        # у каждого числа — где оно взято: «Brent уже $112,4» → предложение новости с этим числом
        shown = " ".join(s.quote for s in out)
        for n in numbers_in(text):
            if n.raw in shown or len(out) >= MAX_SUPPORT:
                continue
            found = self.number_source(n.raw)
            if found is not None:
                out.append(found)
                shown += " " + found.quote
        return out[:MAX_SUPPORT]

    def number_source(self, raw: str) -> ClaimSupport | None:
        """Предложение новости или материала банка, где встречается число (как написано в тексте)."""
        compact = raw.replace(" ", "")
        for sentence in _sentences(self.ctx.event.text):
            if compact in sentence.replace(" ", ""):
                return ClaimSupport(kind="news", ref=self.ctx.event.id, quote=sentence[:QUOTE_MAX])
        for hit in self.ctx.analytics:
            for sentence in _sentences(hit.source.fragment or ""):
                if compact in sentence.replace(" ", ""):
                    return ClaimSupport(kind="bank", ref=hit.source.id, quote=sentence[:QUOTE_MAX])
        return None

    # --- опора по совпадению — у итога и шагов без ссылок ------------------------------------------------

    def support_by_overlap(self, text: str) -> list[ClaimSupport]:
        candidates: list[tuple[int, ClaimSupport]] = []
        quote, score = _best_quote(text, self.ctx.event.text)
        if score >= MIN_OVERLAP:
            candidates.append((score, ClaimSupport(kind="news", ref=self.ctx.event.id, quote=quote)))
        for hit in self.ctx.analytics:
            if hit.stale:
                continue
            quote, score = _best_quote(text, hit.source.fragment or "")
            if score >= MIN_OVERLAP:
                candidates.append((score, ClaimSupport(kind="bank", ref=hit.source.id, quote=quote)))
        want = _stems(text)
        for f in self.features.values():
            label = f"{f.label}: {_shown(f.display if f.display is not None else f.value)}"
            score = len(want & _stems(label))
            if score >= MIN_OVERLAP:
                candidates.append((score, ClaimSupport(kind="company", ref=f.id, quote=label[:QUOTE_MAX])))
        candidates.sort(key=lambda c: -c[0])
        return [c[1] for c in candidates[:2]]

    # --- статус ------------------------------------------------------------------------------------------

    def claim(self, text: str, refs: list[str], origin: str | None = None) -> Claim:
        missing = [] if origin == "estimate" else self.numbers.unsupported(text)  # расчёт по формуле сервиса
        support = self.support_for(text, refs)
        if origin == "hypothesis" or _POSSIBLE.match(text.strip()):
            status = "hypothesis"
        elif support and not missing:
            status = "verified"
        else:
            status = "partly"
        return Claim(text=text, status=status, support=support, unsupported_numbers=missing)


def verify(ctx: AgentContext, insight: Insight, rewritten: int = 0, dropped: int = 0) -> ClaimsSummary:
    """Проверить утверждения карточки, убрать выводы с ненайденным числом и без опоры, заполнить claims."""
    v = Verifier(ctx)
    # расчёты сервиса в карточке — факты: их числа можно повторять в итоге и выводах (в снимке для вопросов
    # расчётов контекста нет — берём их из самой карточки)
    for s in insight.statements():
        if s.origin == "estimate":
            v.numbers.add_text(s.text)
    claims: list[Claim] = []
    removed = 0

    def check_block(items: list[Statement]) -> list[Statement]:
        nonlocal removed
        kept = []
        for s in items:
            c = v.claim(s.text, s.refs, s.origin)
            unfounded = c.status == "partly" and c.unsupported_numbers and not c.support
            if s.origin in ("ai", "data") and unfounded:
                removed += 1  # число ни в каких фактах и опоры нет — такое утверждение не показываем
                continue
            kept.append(s)
            claims.append(c)
        return kept

    if insight.verdict:
        vd = insight.verdict
        claims.append(v.claim(vd.headline, vd.refs))
        claims.append(v.claim(vd.why, vd.refs))
        # шаг — по своим словам и числам, а не по всем ссылкам итога
        claims += [v.claim(step.text, []) for step in vd.steps]
    insight.why_it_matters = check_block(insight.why_it_matters)
    insight.consequences.risks = check_block(insight.consequences.risks)
    insight.consequences.opportunities = check_block(insight.consequences.opportunities)
    bp = insight.bank_position
    if bp and bp.found:
        claims.append(v.claim(bp.statement, [bp.source_id] if bp.source_id else []))

    insight.claims = claims
    summary = ClaimsSummary(
        total=len(claims),
        verified_count=sum(1 for c in claims if c.status == "verified"),
        partly_count=sum(1 for c in claims if c.status == "partly"),
        hypothesis_count=sum(1 for c in claims if c.status == "hypothesis"),
        rewritten=rewritten,
        removed=removed + dropped,
    )
    insight.claims_summary = summary
    return summary
