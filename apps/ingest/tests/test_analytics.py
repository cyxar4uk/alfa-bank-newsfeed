import json
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
    "ЦБ РФ принял решение оставить ключевую ставку неизменной на уровне 14,0%. Формально сигнал пресс-релиза "
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
    assert "rate" in [f.code for f in sources[0].tags.factors]
    assert sources[0].page_ref == "src:alfa:keyrate-2026-09#p1"
    assert sources[0].ocr_engine == "tesseract"
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
    run = ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert len(run.pages) == 2 and run.cached == 0 and engine.calls == 2 and run.errors == []
    assert "x3500" in run.pages[0][0].text  # портрет: длинная сторона 3500 px
    assert (tmp_path / "cache" / "p001.txt").exists()

    again = ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert again.cached == 2 and engine.calls == 2
    assert again.pages[1][0].text == run.pages[1][0].text


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
    from ingest.analytics.ocr import CacheOnlyEngine

    pdf_path = tmp_path / "one.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.save(str(pdf_path))
    doc.close()

    empty = ocr_pages(pdf_path, CacheOnlyEngine("counting", "нет tesseract"), tmp_path / "cache")
    assert empty.pages == [None] and empty.errors == ["стр. 1: нет tesseract"]
    ocr_pages(pdf_path, CountingEngine(), tmp_path / "cache")
    run = ocr_pages(pdf_path, CacheOnlyEngine("counting", "нет tesseract"), tmp_path / "cache")
    assert run.cached == 1 and run.pages[0][0].text.startswith("Страница")


class FailingEngine:
    name = "failing"
    workers = 1

    def __init__(self):
        self.calls = 0

    def recognize(self, image):
        from ingest.analytics.ocr import OcrUnavailable

        self.calls += 1
        raise OcrUnavailable("модель ответила 402: Budget has been exceeded")


def test_engine_error_stops_sending_pages_and_keeps_run_alive(tmp_path: Path):
    pdf_path = tmp_path / "five.pdf"
    doc = pdfium.PdfDocument.new()
    for _ in range(5):
        doc.new_page(595, 842)
    doc.save(str(pdf_path))
    doc.close()

    engine = FailingEngine()
    run = ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert run.pages == [None] * 5
    assert run.errors and "Budget" in run.errors[0]
    assert engine.calls <= 2  # после первой ошибки новые страницы не отправляются
    assert not list((tmp_path / "cache").glob("*.json"))  # ошибка не кэшируется


def test_cache_from_another_pdf_with_same_name_is_ignored(tmp_path: Path):
    from ingest.analytics.pipeline import pdf_digest

    pdf_path = tmp_path / "one.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(595, 842)
    doc.save(str(pdf_path))
    doc.close()
    engine = CountingEngine()
    ocr_pages(pdf_path, engine, tmp_path / "cache")
    cache = tmp_path / "cache" / "p001.json"
    data = json.loads(cache.read_text("utf-8"))
    assert data["pdf_sha"] == pdf_digest(pdf_path)
    data["pdf_sha"] = "другой выпуск"
    cache.write_text(json.dumps(data), "utf-8")
    ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert engine.calls == 2
    cache.write_text("{испорченный json", "utf-8")
    ocr_pages(pdf_path, engine, tmp_path / "cache")
    assert engine.calls == 3


TABLE = (
    "Показатель | 2026П | 2027П\n|---|---|---|\n"
    "Ключевая ставка, конец года | 14,0% | 12,0%\nИнфляция, % дек./дек. | 7,5% | 5,5%"
)


def test_vlm_table_with_caption_kept_as_one_fragment():
    blocks = [block("Табл.2: Основные макроэкономические показатели"), block(TABLE, conf=100.0)]
    frags, report = page_fragments(4, blocks, allow_tables=True)
    assert len(frags) == 1
    assert frags[0].text.startswith("Табл.2: Основные макроэкономические показатели\nПоказатель | 2026П")
    assert "|---|" not in frags[0].text


def test_merge_page_keeps_trusted_tesseract_and_adds_vlm_only_content():
    from ingest.analytics.pipeline import merge_page

    garbled = "Динамика 2 пни МИНЫ совокупных банковских активов помесячно, Кредиты юридическим лицам растут быстрее"
    tess = [block(BODY, conf=95.0), block(garbled, conf=62.0)]
    vlm = [
        block(BODY),
        block("Динамика совокупных банковских активов помесячно: кредиты юридическим лицам растут быстрее активов."),
        block("Табл.1: Прогноз"),
        block(TABLE),
    ]
    merged, report = merge_page(3, tess, vlm)
    engines = [engine for _, engine in merged]
    texts = [f.text for f, _ in merged]
    assert engines.count("tesseract") == 1 and texts[0] == BODY  # дубль надёжного текста из Qwen не берём
    assert any(t.startswith("Табл.1: Прогноз") for t in texts)  # таблицы у Tesseract не было
    assert garbled not in texts  # испорченный фрагмент заменён версией Qwen
    assert report.replaced_by_vlm == 1 and report.added_from_vlm == 2


def test_merge_page_without_vlm_is_plain_tesseract():
    from ingest.analytics.pipeline import merge_page

    merged, report = merge_page(1, [block(BODY)], None)
    assert [(f.text, e) for f, e in merged] == [(BODY, "tesseract")]
    assert report.added_from_vlm == 0


def test_pages_keep_full_text_for_quote_check_and_stale_flag():
    from ingest.analytics.pipeline import build_pages

    material = Material(
        file="steel.pdf", slug="steels-2021", title="Российская сталь", date=date(2021, 4, 15), stale=True
    )
    pages = build_pages(material, [[block("Заголовок"), block(BODY), block("1")]], [[block(TABLE)]])
    page = pages[0]
    assert page.id == "src:alfa:steels-2021#p1"
    assert page.fragment == f"Заголовок\n\n{BODY}\n\n1"  # всё, что распознано, включая короткие блоки
    assert page.vlm_text == TABLE.replace("|---|---|---|\n", "")  # как во фрагментах
    assert page.stale is True
    # цитата из фрагмента дословно находится в тексте страницы
    assert BODY[20:120] in page.fragment


def test_cached_pages_reads_only_existing_cache(tmp_path: Path):
    from ingest.analytics.pipeline import cached_pages

    (tmp_path / "p002.json").write_text(
        '{"engine": "qwen3-vl", "blocks": [{"text": "x", "confidence": 100, "bbox": [0, 0, 1, 1]}]}', "utf-8"
    )
    (tmp_path / "p003.json").write_text('{"engine": "other", "blocks": []}', "utf-8")
    pages = cached_pages(tmp_path, "qwen3-vl", 3)
    assert pages[0] is None and pages[2] is None
    assert pages[1][0].text == "x"


def test_catalog_marks_steel_report_stale():
    stale = [card for card in load_catalog().values() if card.get("stale")]
    assert [card["slug"] for card in stale] == ["steels-2021"]


def test_vlm_repetition_loop_is_cut():
    from ingest.analytics.ocr import cut_loops

    looped = "Начало. " + "либо входить в органы управления таких компаний, " * 40
    assert cut_loops(looped) == "Начало. либо входить в органы управления таких компаний, "
    assert cut_loops("Ставка 14,0%, 14,0%, 14,0%.") == "Ставка 14,0%, 14,0%, 14,0%."


def test_vlm_axis_tables_are_dropped():
    axis = "01.02.19 | 01.07.19 | 01.12.20\n0,5 | 0,7 | 0,9\n1,1 | 1,3 | 1,5"
    frags, report = page_fragments(1, [block(axis)], allow_tables=True)
    assert frags == [] and report.dropped == {"оси и легенды графика": 1}


def test_weak_tesseract_replaced_even_if_vlm_text_overlaps_good_fragments():
    from ingest.analytics.pipeline import merge_page

    clean = "Флоутеры оправдали свою функцию защитного актива и стали самым доходным инструментом на рынке облигаций."
    garbled = "затронувшая. Снижение ключевой. (С Флоутеры оправдали свою ane функцию защитного 40% актива LL самым"
    tess = [block(BODY, conf=95.0), block(garbled, conf=60.0)]
    vlm = [block(BODY), block(clean)]
    merged, report = merge_page(6, tess, vlm)
    texts = [(f.text, e) for f, e in merged]
    assert (BODY, "tesseract") in texts and (clean, "qwen3-vl") in texts
    assert all(t != garbled for t, _ in texts)
    assert report.replaced_by_vlm == 1


def test_slug_of_cyrillic_names_is_unique():
    from ingest.analytics.pipeline import slugify

    a, b = slugify("Обзор рынка.pdf"), slugify("Прогноз.pdf")
    assert a != b and a.startswith("material-")
    assert slugify("Inflation_tracker_02.pdf").startswith("inflation-tracker-02-")


def test_impossible_date_in_text_falls_back_to_file_name():
    assert find_date("30 февраля 2026 г.", "Бонд_Бриф_14092026.pdf") == date(2026, 9, 14)
    assert find_date("30 февраля 2026 г.", "x.pdf") is None


def test_fragment_without_heading_is_tagged_as_body():
    from ingest.analytics.pipeline import tag_fragment

    long_text = "Обзор недели. " * 5 + "Упоминается нефть в середине длинного абзаца без заголовка."
    oil = next(f for f in tag_fragment(long_text).factors if f.code == "commodity_oil_gas")
    assert oil.strength == 0.6 and "в тексте" in oil.evidence[0]
    titled = next(f for f in tag_fragment("Нефть\nЦены выросли.").factors if f.code == "commodity_oil_gas")
    assert titled.strength == 1.0


def test_every_fragment_is_verbatim_in_its_page_text():
    from ingest.analytics.pipeline import build_material, build_pages
    from ingest.analytics.quotes import page_text_for, quote_in_page

    material = Material(file="rate.pdf", slug="keyrate-2026-09", title="Ключевая ставка", date=date(2026, 9, 11))
    tess = [
        [
            block("Ключевая ставка ЦБ РФ"),
            block("8,0% 6,0% 4,0% 2,0%"),  # ось графика между заголовком и текстом — отбрасывается
            block(BODY),
            block("Короткий хвост абзаца."),
            block(BODY.replace("14,0%", "13,5%"), conf=60.0),
        ]
    ]
    vlm = [
        [block("Ключевая ставка ЦБ РФ"), block(BODY.replace("14,0%", "13,5%")), block("Табл.1: Прогноз"), block(TABLE)]
    ]
    fragments, _ = build_material(material, tess, vlm)
    pages = {p.id: p for p in build_pages(material, tess, vlm)}
    assert fragments
    for frag in fragments:
        assert quote_in_page(frag.fragment, page_text_for(frag, pages[frag.page_ref])), frag.fragment
    # пересказ не проходит сверку
    assert not quote_in_page("ЦБ РФ решил взять паузу", pages["src:alfa:keyrate-2026-09#p1"].fragment)
    assert not quote_in_page("", "что угодно")
