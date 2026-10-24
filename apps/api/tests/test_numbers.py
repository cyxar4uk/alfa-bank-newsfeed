from api.numbers import fmt_number, fmt_percent, fmt_rub, russian_numbers
from api.profile import format_rub, format_share


def test_numbers_in_russian():
    assert fmt_number(149.0) == "149"
    assert fmt_number(127.12) == "127,1"
    assert fmt_number(0.0) == "0"
    assert fmt_rub(149.04e9) == "149 млрд ₽"
    assert fmt_rub(127.1e9) == "127,1 млрд ₽"
    assert fmt_rub(934e6) == "934 млн ₽"
    assert fmt_rub(120) == "120 ₽"
    assert fmt_percent(0.59) == "59 %" and fmt_percent(0.004) == "0,4 %"
    # обёртки профиля — то же правило
    assert format_rub(2.5e8) == fmt_rub(2.5e8) == "250 млн ₽"
    assert format_share(0.5) == "50 %"


def test_model_text_fixed():
    assert russian_numbers("выручка 149.0 млрд ₽ и 34.0 млрд ₽") == "выручка 149 млрд ₽ и 34 млрд ₽"
    assert russian_numbers("ставка 14.0 % и 16.5 %") == "ставка 14,0 % и 16,5 %"
    assert russian_numbers("127,1 млрд ₽") == "127,1 млрд ₽"
    # даты и номера не трогаем
    assert russian_numbers("заседание 23.10.2026, версия 1.2") == "заседание 23.10.2026, версия 1.2"


def test_rounding_moves_to_next_unit():
    assert fmt_rub(999.96e6) == "1 млрд ₽"
    assert fmt_rub(999_950) == "1 млн ₽"
