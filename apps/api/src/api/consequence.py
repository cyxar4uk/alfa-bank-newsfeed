"""Что событие меняет для компании — одной фразой с направлением: дороже, дешевле, выгоднее, рискованнее.

Направление берётся только из заголовка и только рядом с предметом: «снизил ставку», «цена Brent обновила
максимум», «рубль укрепился». Лид не читаем — в нём слишком много постороннего («сохранив сигнал», «рост
добычи»). Отрицание («не повысил»), противоречие или неясная сторона компании (продаёт топливо или покупает,
экспорт или импорт) — None: вывод честно скажет «направление пока неясно». Лучше промолчать, чем перевернуть
смысл.
"""

import re

from api.contract import ExposureMap, FeedItem

W = r"(?:\s+\S+){0,3}?\s+"  # до трёх слов между глаголом и предметом
_NOT = re.compile(
    r"(?<!\w)(?:не|без|отказал\w*)\s+(?:\S+\s+)?"
    r"(?:повыс|повыш|сниз|сниж|измен|вырос|упал|укреп|ослаб|подорож|подешев)"
)

_RATE_UP = re.compile(
    rf"(?<!\w)(?:повысил|повышени|поднял|подняти)\w*{W}(?:ключев\w*\s+)?ставк|ставк\w*{W}(?:вырос|повысил|поднял)"
)
_RATE_DOWN = re.compile(
    rf"(?<!\w)(?:снизил|снижени|понизил|уменьшил)\w*{W}(?:ключев\w*\s+)?ставк|ставк\w*{W}(?:снизил|снижен|понизил)"
)
_RATE_HOLD = re.compile(
    rf"(?<!\w)(?:сохранил|сохранить|оставил|оставить)\w*{W}(?:ключев\w*\s+)?ставк"
    rf"|ставк\w*{W}(?:сохран|без изменени)"
)
_PAUSE = re.compile(r"пауз\w* в снижении\s+(?:ключев\w*\s+)?ставк")
_RATE_PERCENT = re.compile(r"ставк\w*[^%\d]{0,30}?(\d+(?:[.,]\d+)?)\s?%")

_OIL = re.compile(r"нефт|brent|urals|баррел|бензин|дизел|топлив")
_PRICE = re.compile(r"(?<!\w)(?:цен|стоимост|котиров|brent|urals|баррел)")
_UP = re.compile(
    r"(?<!\w)(?:подорож|дорожа|вырос|выросл|рост(?!\w)|раст[её]т|растут|превысил|максимум|повысил|повышени)"
)
_DOWN = re.compile(r"(?<!\w)(?:подешев|дешеве|снизил|снижени|упал|упали|падени|минимум|понизил)")

_RUB_UP = re.compile(
    r"рубл\w*\s+(?:укрепил|подорожал|вырос)|доллар\w*\s+(?:опустил|подешевел|снизил|упал)|ниже\s+\d+\s+рубл"
)
_RUB_DOWN = re.compile(
    r"рубл\w*\s+(?:ослаб|подешевел|упал)|доллар\w*\s+(?:вырос|подорожал|превысил)|выше\s+\d+\s+рубл"
)

_INFLATION = re.compile(r"инфляц|(?<!\w)рост\w* цен|(?<!\w)цены")
_INFLATION_DOWN = re.compile(r"(?<!\w)(?:замедл|снизил|снижени)")
_GOV = re.compile(r"госрасход|бюджетн\w* расход|расход\w* бюджет|госзаказ|госзакуп")
_GOV_UP = re.compile(r"(?<!\w)(?:увелич|вырос|рост(?!\w))")
_GOV_DOWN = re.compile(r"(?<!\w)(?:сократ|сокращ|урез|сниз)")
_TAX = re.compile(r"налог|пошлин|утильсбор|акциз")
_TAX_UP = re.compile(r"(?<!\w)(?:повыс|повыш|введ|ввод|ввест|увелич|рост(?!\w))")
_TAX_DOWN = re.compile(r"(?<!\w)(?:сниз|сниж|отмен|обнул|уменьш)")
_DEMAND = re.compile(r"(?<!\w)(?:спрос|продаж|потребител)")


def _number(value: str) -> str:
    """«14,00» → «14», «16,5» — как есть."""
    return re.sub(r"[.,]0+$", "", value)


def _title(item: FeedItem) -> str:
    return item.event.title.casefold().replace("ё", "е")


def _channel(exposure: ExposureMap | None, code: str) -> str:
    factor = next((f for f in exposure.factors if f.code == code), None) if exposure else None
    return (factor.channel.text if factor and factor.channel else "").casefold()


def is_seller(exposure: ExposureMap | None, code: str) -> bool:
    """Компания сама в этой отрасли (торгует топливом), а не покупает её продукт."""
    return _side(exposure, code) == "seller"


def _side(exposure: ExposureMap | None, code: str) -> str | None:
    """Продаёт или покупает: «своя отрасль» — продавец, «в себестоимости / затратах» — покупатель."""
    channel = _channel(exposure, code)
    seller = "своя отрасль" in channel
    buyer = bool(re.search(r"себестоимост|затрат|доставка", channel))
    if seller == buyer:
        return None
    return "seller" if seller else "buyer"


def _direction(text: str, up: re.Pattern, down: re.Pattern) -> str | None:
    if _NOT.search(text):
        return None  # «не повысил», «отказался снижать» — не гадаем
    is_up, is_down = bool(up.search(text)), bool(down.search(text))
    if is_up == is_down:
        return None
    return "up" if is_up else "down"


def _rate(title: str, group: bool) -> str | None:
    debt = "долг группы" if group else "долг"
    m = _RATE_PERCENT.search(title)
    rate = f"Ставка {_number(m.group(1))} %" if m else "Ставка"
    if _NOT.search(title):
        return f"{rate} не меняется — {debt} остаётся дорогим" if "ставк" in title else None
    if _PAUSE.search(title):  # «пауза в снижении ставки» — ставка держится, а не снижается
        return f"{rate} продержится дольше — {debt} дороже"
    down, up = bool(_RATE_DOWN.search(title)), bool(_RATE_UP.search(title))
    if down and not up:
        return f"Ставка снижается — {debt} подешевеет"
    if up and not down:
        return f"Ставка растёт — {debt} дороже"
    if _RATE_HOLD.search(title):
        return f"{rate} продержится дольше — {debt} дороже"
    return None


def _deposit(title: str) -> str | None:
    if _NOT.search(title):
        return None
    if _PAUSE.search(title) or _RATE_HOLD.search(title) or _RATE_UP.search(title):
        return "Высокая ставка держится — депозиты приносят больше"
    if _RATE_DOWN.search(title):
        return "Ставка снижается — доходность депозитов упадёт"
    return None


def _oil(title: str, side: str | None) -> str | None:
    if not (_OIL.search(title) and _PRICE.search(title)) or side is None:
        return None  # не о цене или неясно, продаёт компания топливо или покупает
    direction = _direction(title, _UP, _DOWN)
    if direction is None:
        return None
    if side == "seller":
        return (
            "Нефть дорожает — выручка от топлива выше"
            if direction == "up"
            else "Нефть дешевеет — выручка ниже"
        )
    return (
        "Нефть дорожает — топливо для вас дороже" if direction == "up" else "Нефть дешевеет — топливо дешевле"
    )


def _fx(title: str, channel: str) -> str | None:
    if _NOT.search(title) or re.search(r"не смог|не удалось", title):
        return None
    strong, weak = bool(_RUB_UP.search(title)), bool(_RUB_DOWN.search(title))
    if strong == weak:
        return None
    export, imports = "экспорт" in channel, bool(re.search(r"импорт|поставщик", channel))
    if export and not imports:
        return (
            "Рубль крепче — валютная выручка в рублях меньше" if strong else "Рубль слабее — экспорт выгоднее"
        )
    if imports and not export:
        return "Рубль крепче — импорт дешевле" if strong else "Рубль слабее — импорт дороже"
    return None  # и экспорт, и импорт или ничего — знак для компании неясен


def consequence(item: FeedItem, key: str, exposure: ExposureMap | None) -> str | None:
    """Последствие для компании или None, если направление честно не определить."""
    title = _title(item)
    group = bool(item.group_impact and item.group_impact.affected_count)
    if key == "rate":
        return _rate(title, group)
    if key == "deposit_yield":
        return _deposit(title)
    if key == "commodity_oil":
        return _oil(title, _side(exposure, key))
    if key == "fx":
        return _fx(title, _channel(exposure, key))
    if key == "inflation" and _INFLATION.search(title):
        direction = _direction(title, _UP, _INFLATION_DOWN)
        if direction == "up":
            return "Цены растут — издержки выше"
        if direction == "down":
            return "Инфляция замедляется — издержки растут медленнее"
    if key == "gov" and _GOV.search(title):
        direction = _direction(title, _GOV_UP, _GOV_DOWN)
        if direction == "up":
            return "Госрасходы растут — госзаказа больше"
        if direction == "down":
            return "Госрасходы сокращаются — госзаказ под риском"
    if key == "tax_regulation" and _TAX.search(title):
        direction = _direction(title, _TAX_UP, _TAX_DOWN)
        if direction == "up":
            return "Налоги и пошлины растут — нагрузка выше"
        if direction == "down":
            return "Налоги и пошлины снижаются — нагрузка ниже"
    if key == "consumer" and _DEMAND.search(title):
        direction = _direction(title, _UP, _DOWN)
        if direction == "up":
            return "Спрос растёт — продажи могут вырасти"
        if direction == "down":
            return "Спрос слабеет — продажи под риском"
    return None
