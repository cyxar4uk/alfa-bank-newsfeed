"""Числа для людей — одно правило на весь API: дробь через запятую, целые без «,0».

«149 млрд ₽», «127,1 млрд ₽», «14 %», «0,4 %». Текст модели, где число пришло с точкой («149.0 млрд ₽»),
чинит `russian_numbers`.
"""

import re

_UNITS = ((1e12, "трлн"), (1e9, "млрд"), (1e6, "млн"), (1e3, "тыс."))
# число с точкой перед единицей: «149.0 млрд», «14.5 %», «2.5 п.п.»; даты «23.10.2026» не трогает
_DOTTED = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])(?=\s?(?:трлн|млрд|млн|тыс|₽|%|п\.\s?п))")
# «149,0 млрд» → «149 млрд»
_ZERO = re.compile(r"(?<![\d,])(\d+),0+(?![\d])(?=\s?(?:трлн|млрд|млн|тыс|₽|%|п\.\s?п))")


def fmt_number(value: float, digits: int = 1) -> str:
    """«149», «127,1», «0,35»: округление до `digits` знаков, без хвостовых нулей."""
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",") if text not in ("-0", "") else "0"


def fmt_rub(amount: float) -> str:
    """«149 млрд ₽», «934 млн ₽», «7,5 тыс. ₽», «120 ₽»."""
    for scale, unit in _UNITS:
        if abs(amount) >= scale:
            return f"{fmt_number(amount / scale)} {unit} ₽"
    return f"{fmt_number(amount, 0)} ₽"


def fmt_percent(share: float) -> str:
    """Доля 0–1 → «59 %», «0,4 %» (меньше процента — с одним знаком)."""
    percent = share * 100
    return f"{fmt_number(percent, 0 if abs(percent) >= 1 else 1)} %"


def russian_numbers(text: str) -> str:
    """Числа в свободном тексте — по-русски: «149.0 млрд ₽» → «149 млрд ₽», «14.5 %» → «14,5 %»."""
    text = _DOTTED.sub(lambda m: f"{m.group(1)},{m.group(2)}", text)
    return _ZERO.sub(lambda m: m.group(1), text)
