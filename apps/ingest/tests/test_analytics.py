from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

from ingest.analytics.fragments import MAX_CHARS, page_fragments, split_long
from ingest.analytics.ocr import MockVisionClient, OcrBlock, VisionLlmEngine, blocks_from_tsv, join_lines
from ingest.analytics.pipeline import Material, build_material, find_date, load_catalog, ocr_pages

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def word(block, par, line, n, text, conf=95, left=0, top=0):
    return f"5\t1\t{block}\t{par}\t{line}\t{n}\t{left}\t{top}\t50\t20\t{conf}\t{text}"


def test_tsv_words_grouped_into_paragraphs_with_hyphenation():
    tsv = "\n".join(
        [
            HEADER,
            "1\t1\t0\t0\t0\t0\t0\t0\t2000\t3000\t-1\t",
            word(1, 1, 1, 1, "Ставка", left=10, top=10),
            word(1, 1, 1, 2, "без", left=70, top=10),
            word(1, 1, 2, 1, "измене-", conf=80, left=10, top=40),
            word(1, 1, 3, 1, "ния", conf=90, left=10, top=70),
            word(2, 1, 1, 1, "Второй", left=10, top=200),
            word(2, 1, 1, 2, "абзац", left=80, top=200),
        ]
    )
    blocks = blocks_from_tsv(tsv)
    assert [b.text for b in blocks] == ["Ставка без изменения", "Второй абзац"]
    assert blocks[0].confidence == pytest.approx((95 + 95 + 80 + 90) / 4, abs=0.1)
    assert blocks[0].bbox == (10, 10, 110, 80)


def test_join_lines_keeps_hyphen_before_capital():
    assert join_lines(["Санкт-", "Петербург"]) == "Санкт-Петербург"
    assert join_lines(["пресс-", "релиз"]) == "прессрелиз"
    assert join_lines(["первая", "", "вторая"]) == "первая вторая"


def test_vision_engine_splits_paragraphs_from_model_text():
    engine = VisionLlmEngine(MockVisionClient("Заголовок\n\nПервый абзац\nпродолжение\n\n\nВторой"))
    blocks = engine.recognize(Image.new("L", (100, 200), 255))
    assert [b.text for b in blocks] == ["Заголовок", "Первый абзац продолжение", "Второй"]
    assert engine.name == "qwen3-vl"


def block(text, conf=95.0):
    return OcrBlock(text=text, confidence=conf, bbox=(0, 0, 10, 10))


BODY = (
    "ЦБ РФ принял решение оставить ставку неизменной на уровне 14,0%. Формально сигнал пресс-релиза "
    "остался нейтральным, однако риторика стала жестче."
)


def test_page_fragments_drop_boilerplate_tables_and_low_confidence():
    blocks = [
        block("Центр макроэкономического анализа"),
        block("Ключевая ставка ЦБ РФ"),
        block(BODY),
        block("2025 2026 14,0 13,5 12,0 5,6 7,6 4,1 5,4"),
        block("Альфа-Банк, 2026 г. Все права защищены. Генеральная лицензия ЦБ РФ № 1326"),
        block("Неразборчивый текст скана, который распознался плохо и не годится", conf=30),
        block("1"),
    ]
    frags, report = page_fragments(1, blocks)
    assert len(frags) == 1
    assert frags[0].text.startswith("Ключевая ставка ЦБ РФ\nЦБ РФ принял решение")
    assert report.dropped == {
        "дисклеймер или колонтитул": 3,
        "таблица или цифры": 1,
        "низкая уверенность распознавания": 1,
    }


def test_long_paragraph_split_by_sentences():
    text = " ".join(f"Предложение номер {i} про инфляцию и ставку." for i in range(80))
    parts = split_long(text)
    assert len(parts) > 1
    assert all(len(p) <= MAX_CHARS for p in parts)
    assert " ".join(parts) == text


def test_build_material_ids_pages_dates_and_tags():
    material = Material(file="rate.pdf", slug="keyrate-2026-09", title="Ключевая ставка ЦБ РФ", date=date(2026, 9, 11))
    sources, reports = build_material(material, [[block(BODY)], [block("1")], [block(BODY), block(BODY)]])
    assert [s.id for s in sources] == [
        "src:alfa:keyrate-2026-09#p1-1",
        "src:alfa:keyrate-2026-09#p3-1",
        "src:alfa:keyrate-2026-09#p3-2",
    ]
    assert sources[0].kind == "alfa_analytics"
    assert sources[0].page == 1 and sources[0].file == "rate.pdf"
    assert sources[0].published_at.isoformat() == "2026-09-11T00:00:00+03:00"
    assert "ключевая ставка" in sources[0].tags.topics
    assert reports[1].kept == 0


def test_find_date_from_text_or_file_name():
    assert find_date("Центр анализа 11 сентября 2026 г. Ключевая ставка", "x.pdf") == date(2026, 9, 11)
    assert find_date("без даты", "Бонд_Бриф_14092026.pdf") == date(2026, 9, 14)
    assert find_date("без даты", "report.pdf") is None


def test_catalog_covers_case_materials():
    catalog = load_catalog()
    assert len(catalog) == 9
    assert all({"slug", "title", "date"} <= set(card) for card in catalog.values())


class CountingEngine:
    name = "counting"

    def __init__(self):
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return [block(f"Страница размером {image.size[0]}x{image.size[1]}. " + BODY)]


def test_ocr_pages_renders_each_page_and_uses_cache(tmp_path: Path):
    pdf_path = tmp_path / "two.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.new_page(842, 595)
    doc.save(str(pdf_path))
    doc.close()

    engine = CountingEngine()
    pages, cached = ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert len(pages) == 2 and cached == 0 and engine.calls == 2
    assert "x3500" in pages[0][0].text  # портрет: длинная сторона 3500 px
    assert (tmp_path / "cache" / "p001.txt").exists()

    pages_again, cached = ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert cached == 2 and engine.calls == 2
    assert pages_again[1][0].text == pages[1][0].text


def test_chart_captions_and_axis_debris_are_dropped():
    blocks = [
        block("Рис. 3: Сальдированный финансовый результат компаний, накопленным итогом, трлн руб."),
        block("Источники: Росстат, Альфа-Банк"),
        block("Янв Фев Мар о я о ° en Ф ох og о Номинальные зарплаты % г/г т. Ш № О с"),
        block(BODY),
    ]
    frags, report = page_fragments(2, blocks)
    assert [f.text for f in frags] == [BODY]
    assert report.dropped == {"подпись к графику": 2, "оси и легенды графика": 1}


def test_cache_only_engine_rebuilds_from_cache_and_fails_without_it(tmp_path: Path):
    from ingest.analytics.ocr import CacheOnlyEngine, OcrUnavailable

    pdf_path = tmp_path / "one.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.save(str(pdf_path))
    doc.close()

    with pytest.raises(OcrUnavailable):
        ocr_pages(pdf_path, CacheOnlyEngine("counting", "нет tesseract"), tmp_path / "cache")
    ocr_pages(pdf_path, CountingEngine(), tmp_path / "cache")
    pages, cached = ocr_pages(pdf_path, CacheOnlyEngine("counting", "нет tesseract"), tmp_path / "cache")
    assert cached == 1 and pages[0][0].text.startswith("Страница")
