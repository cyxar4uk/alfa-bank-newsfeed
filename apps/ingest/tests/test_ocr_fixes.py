"""Исправление слов Tesseract по тексту Qwen3-VL и проверка распознанной аналитики в репозитории."""

import json
import re
from pathlib import Path

import pytest

from ingest.analytics.ocr import OcrBlock
from ingest.analytics.ocr_fixes import absent_share, fix_blocks, fix_text, fix_word, isin_ok, reference
from ingest.analytics.pipeline import GARBAGE_ABSENT_SHARE, merge_page

DERIVED = Path(__file__).resolve().parents[3] / "data" / "raw" / "derived"
QWEN = (
    "При этом наш прогноз по ставке на конец 2027 г. остается на уровне 12,0%. Этот фактор выглядит основным. "
    "Рост вакансий за лето 2026 г. составил 12%, оборот торговли — 5,3% г/г (см. Рис. 3). Цена 70 $/барр., "
    "млрд руб. Подход к оценке ключевой ставки. Продолжит воздействовать на цены. Выпуск RU000A10B3A6. "
    "Рейтинг BBB, МТС. Валовое накопление основного капитала. На топ-10 эмитентов."
)


@pytest.fixture
def ref():
    return reference(QWEN)


@pytest.mark.parametrize(
    ("word", "fixed"),
    [
        ("KOHeL", "конец"),  # «L» без пары — любая буква, вариант один
        ("Puc", "Рис"),
        ("py6", "руб"),
        ("6app", "барр"),
        ("ключевои", "ключевой"),  # «й» прочитана как «и» после гласной
        ("воздеиствовать", "воздействовать"),
        ("RUOOOA10B3A6", "RU000A10B3A6"),  # в коде O вместо 0 — тот же код у Qwen
    ],
)
def test_misread_words_are_fixed(ref, word, fixed):
    assert fix_word(word, ref, "на", "2027") == fixed


@pytest.mark.parametrize(
    "word",
    [
        "Вакансии",  # верная форма, которой нет у Qwen; у Qwen «вакансий», но «и» здесь не после гласной
        "BBB",  # рейтинги и аббревиатуры латиницей не трогаем
        "MTC",
        "4K26",  # код с цифрами, которого нет у Qwen
        "2026",
        "HeadHunter",  # латинское название, русского варианта у Qwen нет
        "прогнозы",  # верное слово, которого случайно нет у Qwen
        "a",  # одна буква — без контекста не решить
    ],
)
def test_correct_or_unknown_words_are_kept(ref, word):
    assert "вакансии" not in ref and "прогнозы" not in ref  # правило проверяется, а не ранний выход
    assert fix_word(word, ref, "на", "уровне") is None


def test_ambiguous_word_is_resolved_by_neighbour_or_kept(ref):
    # «stom»: у Qwen есть «этом» и «этот»; «При этом» — пара слов из текста Qwen
    assert fix_word("stom", ref, "При", "увеличение") == "этом"
    assert fix_word("stom", ref, "Вдобавок", "увеличение") is None


def test_short_words_only_inside_russian_phrase(ref):
    ref2 = reference("остается на уровне")
    assert fix_word("Ha", ref2, "остается", "уровне") == "на"
    assert fix_word("Ha", ref2, "2026", "uroven") is None
    # обрывки легенды графика — не фраза: «4 А ee П 2»
    assert fix_word("ee", reference("ее рост, и ее доля"), "А", "П") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("на эмитентах. Ha топ-10 приходится", "на эмитентах. На топ-10 приходится"),  # начало предложения
        ("ставка остается Ha уровне", "ставка остается на уровне"),
        ("Валовое накопление OCHOBHOFO капитала", "Валовое накопление основного капитала"),  # жирное строчное
        ("12 млрд. py6. в год", "12 млрд. руб. в год"),  # точка сокращения — не конец предложения
        ("(см Puc.3)", "(см Рис.3)"),  # имя собственное и в середине фразы с заглавной
    ],
)
def test_case_follows_sentence_not_tesseract(text, expected):
    ref = reference(QWEN + " Ставка остается на уровне 14%. Эмитентах.")
    assert fix_text(text, ref)[0] == expected


def test_fix_text_keeps_everything_else(ref):
    text = "При stom наш прогноз по ставке на KOHeL 2027 r., рост 5,3% rir (см Puc.3)."
    fixed, found = fix_text(text, ref)
    assert fixed == "При этом наш прогноз по ставке на конец 2027 г., рост 5,3% г/г (см Рис.3)."
    assert ("KOHeL", "конец") in found and ("r.", "г.") in found and ("rir", "г/г") in found


def test_patterns_need_the_same_in_qwen():
    assert fix_text("летом 2026 r., рост 5,3% rir", reference("летом 2026 года, рост 5,3% за год"))[1] == []


def test_isin_check_digit_guards_code_from_qwen():
    assert isin_ok("RU000A10B3A6") and not isin_ok("RU000A10B3A7") and not isin_ok("RUOOOA10B3A6")
    # Qwen ошибся в коде (контрольная цифра не сходится) — код Tesseract не трогаем
    assert fix_word("RUOOOA10B3A7", reference("Выпуск RU000A10B3A7."), "Выпуск", None) is None


def test_without_reference_nothing_changes():
    blocks = [OcrBlock("прогноз на KOHeL 2027 r.", 95.0, (0, 0, 1, 1))]
    assert fix_blocks(blocks, None) == (blocks, [])
    assert fix_text("прогноз на KOHeL", reference(""))[1] == []


def test_garbage_fragment_is_dropped_but_clean_table_kept():
    clean = OcrBlock(
        "Ключевая ставка ЦБ РФ сохранена на уровне 14,0%, риторика стала жестче. Мы ожидаем паузы до конца года.",
        95.0,
        (0, 0, 1, 1),
    )
    junk = OcrBlock(
        "Недельная инфляция, % н/ниее ммм очучуоуохоооосссв вазаазаа SOA AN MOA NN AH NO ODO TA OTR TH NM mmm",
        74.0,
        (0, 0, 1, 1),
    )
    vlm = [
        OcrBlock(
            "Ключевая ставка ЦБ РФ сохранена на уровне 14,0%, риторика стала жестче. Мы ожидаем паузы до конца года.",
            0.0,
            (0, 0, 1, 1),
        )
    ]
    share, words = absent_share(junk.text, reference(vlm[0].text))
    assert share >= GARBAGE_ABSENT_SHARE and words >= 8
    merged, report = merge_page(1, [clean, junk], vlm)
    texts = [f.text for f, _ in merged]
    assert clean.text in texts and not any("очучуо" in t for t in texts)
    assert report.dropped.get("мусор распознавания") == 1


# --- данные в репозитории --------------------------------------------------------------------------

# коды облигаций мешают кириллицу с латиницей по-настоящему: БО-001Р-05, 001Р-SBER51
BOND_CODE = re.compile(r"^(?:БО-)?\d{3}[PР](?:-[0-9A-Za-z]+)?$|^\d{3}[PР]-[0-9A-Z]+$")
WORD = re.compile(r"[\w\-]+")


def _jsonl(name: str) -> list[dict]:
    path = DERIVED / name
    if not path.exists():
        pytest.skip(f"нет {path}")
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def test_no_words_mixing_latin_and_cyrillic_in_derived():
    bad = []
    for name, fields in (("alfa_pages.jsonl", ("fragment", "vlm_text")), ("alfa_fragments.jsonl", ("fragment",))):
        for rec in _jsonl(name):
            for field in fields:
                for w in WORD.findall(rec.get(field) or ""):
                    if re.search("[A-Za-z]", w) and re.search("[А-Яа-яЁё]", w) and not BOND_CODE.match(w):
                        bad.append((rec["id"], w))
    assert bad == []


def test_derived_pages_have_no_fixable_words_left():
    """Повторный проход исправлений по страницам репозитория ничего не находит: пайплайн уже всё применил.

    Как и пайплайн, правим по блокам (в тексте страницы они разделены пустой строкой): соседи — только свои."""
    left = []
    for page in _jsonl("alfa_pages.jsonl"):
        ref = reference(page.get("vlm_text"))
        for block in page["fragment"].split("\n\n"):
            left += [(page["id"], was, now) for was, now in fix_text(block, ref)[1]]
    assert left == []
    assert any(page.get("ocr_fixes") for page in _jsonl("alfa_pages.jsonl"))


def test_known_misreads_are_gone_and_fragments_still_verbatim():
    from ingest.analytics.quotes import quote_in_page
    from ingest.models import Source

    pages = {p["id"]: p for p in _jsonl("alfa_pages.jsonl")}
    keyrate = pages["src:alfa:keyrate-2026-09#p1"]["fragment"]
    assert "на конец 2027 г." in keyrate and "KOHeL" not in keyrate
    for frag in _jsonl("alfa_fragments.jsonl"):
        page = pages[frag["page_ref"]]
        text = page["vlm_text"] if frag.get("ocr_engine") == "qwen3-vl" else page["fragment"]
        assert quote_in_page(frag["fragment"], text), frag["id"]
        Source.model_validate(frag)


def _blocks(*items):
    return [OcrBlock(text, conf, (0, 0, 1, 1)) for text, conf in items]


GOOD = "Ключевая ставка ЦБ РФ сохранена на уровне 14,0%, риторика стала жестче. Мы ожидаем паузы до конца года."
JUNK = "Недельная инфляция, % н/ниее ммм очучуоуохоооосссв вазаазаа SOA AN MOA NN AH NO ODO TA OTR TH NM mmm"


def test_garbage_covered_by_qwen_is_replaced():
    legend = (
        "Недельная инфляция ускорилась: продовольствие, базовые услуги, туристические услуги и плодоовощи подорожали."
    )
    vlm = _blocks((GOOD, 95.0), (legend, 95.0))
    junk = "Недельная инфляция, % н/ниее ммм очучуоуо продовольствие базовые услуги туристические SOA NN плодоовощи"
    merged, report = merge_page(1, _blocks((GOOD, 95.0), (junk, 74.0)), vlm)
    assert report.replaced_by_vlm == 1 and not report.dropped.get("мусор распознавания")
    assert [engine for _, engine in merged].count("qwen3-vl") == 1


def test_confident_text_is_never_dropped_as_garbage():
    merged, report = merge_page(1, _blocks((GOOD, 95.0), (JUNK, 90.0)), _blocks((GOOD, 95.0)))
    assert any("очучуо" in f.text for f, _ in merged) and not report.dropped.get("мусор распознавания")
