"""Значимость события для компании в карточке — согласованная с тем, на чём построено объяснение.

Формальная оценка (ранжирование или запасная формула) видит только связи из разметки события: факторы новости
и её отрасли в цепочке контрагентов. Агент находит и другие: новость про утильсбор на грузовики размечена как
машиностроение (29), а компания торгует автозапчастями (45): значительная доля платежей уходит компаниям из торговли автомобилями (ОКВЭД 45).
Формула даёт 0,04, а «почему важно вам» говорит про 51 % платежей.

Поэтому к формальной оценке добавляются слагаемые по факторам и каналам, которые карточка реально использует:
сила фактора у компании × сила связи с событием. Связь из разметки — её сила; канал цепочки — его сила; связь,
которую нашёл агент, а в разметке её нет, — с понижающим весом и пометкой. Итог — наибольшее из формальной
оценки и слагаемых.
"""

from dataclasses import dataclass

from api.agent.context import AgentContext
from api.agent.ports import LEVEL_RANK
from api.contract import Relevance

# связь, которую нашёл агент, а парсер не разметил: доверяем ей меньше, чем размеченной
AGENT_LINK_WEIGHT = 0.5
CHANNEL_KINDS = {"direct", "buyers", "suppliers", "group"}


@dataclass
class Term:
    code: str
    label: str
    value: float
    exposure: float
    link: float
    source: str  # tag | chain | agent

    def describe(self) -> str:
        how = {"tag": "связь из разметки", "chain": "канал цепочки", "agent": "связь найдена агентом"}[
            self.source
        ]
        return f"{self.label}: {self.exposure:.2f} × {self.link:.2f} = {self.value:.2f} ({how})"


def _strength(f) -> float:
    return f.strength if f.strength is not None else LEVEL_RANK.get(f.level, 0) / 3


def terms_for(ctx: AgentContext, covered: set[str], stated: set[str] | None = None) -> list[Term]:
    """Слагаемые по факторам и каналам, которые использует карточка.

    Связь, которой нет в разметке, засчитывается только по фактору, явно названному в выводе (`stated`):
    ссылка на признак задевает много факторов карты сразу, а гипотеза — ещё не вывод.
    """
    stated = covered if stated is None else stated
    exposure = {f.code: f for f in ctx.exposure}
    tags = {t.code: t.strength for t in ctx.event.factors}
    channels = {ch.factor: ch for ch in ctx.chain.channels if ch.factor}
    by_kind: dict[str, float] = {}
    for ch in ctx.chain.channels:
        by_kind[ch.kind] = max(by_kind.get(ch.kind, 0.0), ch.strength or 0.0)
    out: list[Term] = []
    for code in sorted(covered):
        if code in CHANNEL_KINDS:
            if code in by_kind:
                out.append(Term(code, f"канал {code}", round(by_kind[code], 4), by_kind[code], 1.0, "chain"))
            continue
        f = exposure.get(code)
        if f is None or LEVEL_RANK.get(f.level, 0) < 1:
            continue
        s = _strength(f)
        if code in channels and channels[code].strength is not None:
            ch = channels[code]
            out.append(
                Term(
                    code,
                    f.label,
                    round(ch.strength, 4),
                    ch.share or s,
                    ch.strength / (ch.share or 1),
                    "chain",
                )
            )
        elif code in tags:
            out.append(Term(code, f.label, round(s * tags[code], 4), s, tags[code], "tag"))
        elif code in stated:
            out.append(Term(code, f.label, round(s * AGENT_LINK_WEIGHT, 4), s, AGENT_LINK_WEIGHT, "agent"))
    return sorted(out, key=lambda t: -t.value)


def formula(ctx: AgentContext) -> Relevance:
    """Запасная формальная оценка без ранжирования: событие по фактору × сила фактора, лучший канал."""
    exposure = {f.code: f for f in ctx.exposure}
    best, refs = 0.0, []
    for tag in ctx.event.factors:
        f = exposure.get(tag.code)
        if f is None:
            continue
        if tag.strength * _strength(f) > best:
            best, refs = tag.strength * _strength(f), f.refs
    for ch in ctx.chain.channels:
        if (ch.strength or 0) > best:
            best, refs = ch.strength or 0, ch.refs
    return Relevance(
        score=round(min(best, 1.0), 2),
        reason="событие касается того, от чего зависит бизнес компании",
        refs=refs,
    )


def combine(formal: Relevance, terms: list[Term]) -> tuple[float, str]:
    """Итоговая оценка и откуда она: формальная или по фактору карточки."""
    top = terms[0] if terms else None
    if top is None or top.value <= formal.score:
        return round(min(formal.score, 1.0), 2), "формальная оценка"
    return round(min(top.value, 1.0), 2), top.describe()
