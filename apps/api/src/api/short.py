"""Короткая строка «для вас» к событию ленты: до SHORT_MAX знаков, с числом из данных, без кодов и пометок.

Честной короткой строки нет (нет числа или не помещается без обрезки) — None: экран возьмёт `channel_text`.

Строится из главного слагаемого оценки: фактор карты («Стоимость заёмных денег: собственный кредит в банке,
кредиты у 11 компаний группы») или канал цепочки («Через покупателей: общепит — 53 % поступлений»).
"""

import re

from api.contract import ChainChannel
from api.profile import format_share

SHORT_MAX = 90

# коды ОКВЭД («46.71», «35.11.1», «ОКВЭД 46.71») и класс в скобках («(56)»); «16.5 %» — не код
_CODE = re.compile(r"\s*(?:ОКВЭД\s*)?(?<![\w.])\d{2}\.\d{2}(?:\.\d+)*(?!\w|\.\d)|\s*\(\d{2}\)")
_EMPTY_PARENS = re.compile(r"\s*\(\s*[,;\s]*\)")
# служебные пометки расчёта: оценка по отрасли, направление, событие за рубежом
_SERVICE = re.compile(
    r"\s*\((?:оценка|событие за рубежом)[^)]*\)"
    r"|\s*—\s*направление по отрасли"
    r"|\s*;?\s*направление — [^;]*"
    r"|\s*;\s*что они импортируют — оценка по отрасли"
)
_PARENS = re.compile(r"\s*\([^)]*\)")


def _has_number(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


# короткие названия факторов для строки «для вас»; не указан — название из карты
HEADS = {
    "rate": "Стоимость долга",
    "deposit_yield": "Доходность остатков",
    "fx": "Курс",
    "ved_logistics": "ВЭД",
    "consumer": "Спрос",
    "labor": "Зарплаты",
    "gov": "Госзаказ и бюджет",
    "commodity_oil": "Нефть и топливо",
    "commodity_metals": "Металлы",
    "commodity_gold": "Золото",
    "commodity_fertilizers": "Удобрения",
    "commodity_agro": "Агросырьё",
    "inflation": "Издержки",
    "region": "Регион",
    "tax_regulation": "Налоги и отчётность",
}


def _honest(line: str) -> str | None:
    """Строка годится, только если в ней есть число из данных и она помещается целиком."""
    if len(line) > SHORT_MAX:
        line = _PARENS.sub("", line)  # перечни стран и отраслей в скобках — первыми
    return line if len(line) <= SHORT_MAX and _has_number(line) else None


def factor_short(code: str, label: str, text: str) -> str | None:
    """«{фактор}: {канал}» — первая часть канала и, если в ней нет числа, следующая часть с числом."""
    head = HEADS.get(code, label)
    clean = _EMPTY_PARENS.sub("", _CODE.sub("", _SERVICE.sub("", text)))
    parts = [p.strip().removeprefix("также ").strip() for p in clean.split(";")]
    parts = [p.removeprefix(f"{head}: ") for p in parts if p]  # «ВЭД: ВЭД: Китай»
    body = next((p for p in parts if _has_number(p)), None)
    if body is None:
        return None
    if parts[0] != body:
        joined = _honest(f"{head}: {parts[0]}, {body}")  # «собственный кредит в банке, кредиты у 11 компаний»
        if joined:
            return joined.replace("своя отрасль", "ваша отрасль")
    line = _honest(f"{head}: {body}")
    return line.replace("своя отрасль", "ваша отрасль") if line else None


def clean_channel(text: str) -> str:
    """Первая часть канала без кодов, пометок и перечней: для вывода, когда строки «для вас» нет."""
    clean = _EMPTY_PARENS.sub("", _CODE.sub("", _SERVICE.sub("", text)))
    first = clean.split(";")[0].strip()
    first = _PARENS.sub("", first) if len(first) > SHORT_MAX else first
    parts = first.split(" → ")
    if len(parts) >= 3 and parts[0] == "событие":
        # цепочка «событие → общепит → ваши покупатели: 469 компаний, 53 % поступлений → вы»
        who, _, rest = parts[2].partition(": ")
        sector = parts[1].strip()
        if who.startswith(("своя отрасль", "ваша отрасль")):
            first = f"ваша отрасль «{sector}»"
        else:
            first = f"{who} из отрасли «{sector}»" + (f": {rest}" if rest else "")
    return first.replace("своя отрасль", "ваша отрасль")


def chain_short(channel: ChainChannel) -> str | None:
    sector = channel.sector or "смежная отрасль"
    share = format_share(channel.share)
    if channel.kind == "buyers":
        return _honest(f"Через покупателей: {sector} — {share} поступлений")
    if channel.kind == "suppliers":
        return _honest(f"Через поставщиков: {sector} — {share} платежей")
    if channel.kind == "group":
        return _honest(f"Через компании группы: {sector} — {share} выручки группы")
    return None  # своя отрасль: числа нет
