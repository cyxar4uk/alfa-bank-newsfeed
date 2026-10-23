"""Аналитика банка: PDF-сканы → картинки страниц → распознавание (с кэшем) → фрагменты Source."""

import json
import os
import re
import tomllib
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from importlib import resources
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from ingest.analytics.fragments import PageReport, page_fragments
from ingest.analytics.ocr import OcrBlock, OcrEngine, OcrUnavailable
from ingest.models import Source
from ingest.news.normalize import MSK
from ingest.tagging.rules import tag_text

PUBLISHER = "Альфа-Банк"
# длинная сторона страницы ≈ 3500 px — это 300 dpi для A4
RENDER_LONG_SIDE = 3500
_MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
_TEXT_DATE = re.compile(rf"(\d{{1,2}})\s+({'|'.join(_MONTHS)})\s+(20\d\d)", re.I)
_NAME_DATE = re.compile(r"(\d{2})(\d{2})(20\d\d)")


@dataclass
class Material:
    file: str
    slug: str
    title: str
    date: date | None
    date_note: str = ""


@dataclass
class MaterialReport:
    file: str
    slug: str
    pages: int
    fragments: int
    mean_confidence: float
    cached_pages: int
    page_reports: list[PageReport] = field(default_factory=list)
    error: str | None = None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def load_catalog() -> dict[str, dict]:
    raw = resources.files("ingest.analytics").joinpath("catalog.toml").read_text("utf-8")
    return {_nfc(k): v for k, v in tomllib.loads(raw).get("materials", {}).items()}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-") or "material"


def find_date(text: str, file_name: str) -> date | None:
    m = _TEXT_DATE.search(text)
    if m:
        return date(int(m.group(3)), _MONTHS.index(m.group(2).lower()) + 1, int(m.group(1)))
    m = _NAME_DATE.search(file_name)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def describe(pdf: Path, catalog: dict[str, dict], first_page_text: str) -> Material:
    card = catalog.get(_nfc(pdf.name))
    if card:
        return Material(
            file=pdf.name,
            slug=card["slug"],
            title=card["title"],
            date=date.fromisoformat(card["date"]),
            date_note=card.get("date_note", ""),
        )
    return Material(file=pdf.name, slug=slugify(pdf.name), title=pdf.stem, date=find_date(first_page_text, pdf.name))


def render_page(page: pdfium.PdfPage) -> Image.Image:
    w, h = page.get_size()
    return page.render(scale=RENDER_LONG_SIDE / max(w, h), grayscale=True).to_pil()


def _cache_path(cache_dir: Path, page_no: int) -> Path:
    return cache_dir / f"p{page_no:03d}.json"


def _read_cache(path: Path, engine: OcrEngine) -> list[OcrBlock] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text("utf-8"))
    if data.get("engine") != engine.name:
        return None
    return [OcrBlock(b["text"], b["confidence"], tuple(b["bbox"])) for b in data["blocks"]]


def _write_cache(path: Path, pdf: Path, page_no: int, engine: OcrEngine, blocks: list[OcrBlock]) -> None:
    payload = {"file": pdf.name, "page": page_no, "engine": engine.name, "blocks": [b.to_dict() for b in blocks]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    path.with_suffix(".txt").write_text("\n\n".join(b.text for b in blocks), "utf-8")


def ocr_pages(
    pdf: Path, engine: OcrEngine, cache_dir: Path, force: bool = False, workers: int | None = None
) -> tuple[list[list[OcrBlock]], int]:
    """Распознаёт все страницы, распознанные тем же движком берёт из кэша. Возвращает блоки и число кэшированных.

    Рендер идёт по очереди (pdfium не потокобезопасен), распознавание страниц — параллельно.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    pages: dict[int, list[OcrBlock]] = {}
    try:
        with ThreadPoolExecutor(max_workers=workers or os.cpu_count() or 2) as pool:
            futures = {}
            for i in range(len(doc)):
                page_no = i + 1
                cached = None if force else _read_cache(_cache_path(cache_dir, page_no), engine)
                if cached is not None:
                    pages[page_no] = cached
                else:
                    futures[pool.submit(engine.recognize, render_page(doc[i]))] = page_no
            for future in as_completed(futures):
                page_no = futures[future]
                pages[page_no] = future.result()
                _write_cache(_cache_path(cache_dir, page_no), pdf, page_no, engine, pages[page_no])
    finally:
        doc.close()
    return [pages[n] for n in sorted(pages)], len(pages) - len(futures)


def build_material(material: Material, pages: list[list[OcrBlock]]) -> tuple[list[Source], list[PageReport]]:
    published = (
        datetime(material.date.year, material.date.month, material.date.day, tzinfo=MSK) if material.date else None
    )
    sources, reports = [], []
    for page_no, blocks in enumerate(pages, start=1):
        fragments, report = page_fragments(page_no, blocks)
        reports.append(report)
        for n, frag in enumerate(fragments, start=1):
            sources.append(
                Source(
                    id=f"src:alfa:{material.slug}#p{page_no}-{n}",
                    kind="alfa_analytics",
                    title=material.title,
                    publisher=PUBLISHER,
                    published_at=published,
                    fragment=frag.text,
                    tags=tag_text(f"{material.title}\n{frag.text}"),
                    page=page_no,
                    file=material.file,
                    ocr_confidence=frag.confidence,
                )
            )
    return sources, reports


def process_folder(
    pdf_dir: Path, cache_root: Path, engine: OcrEngine, force: bool = False
) -> tuple[list[Source], list[MaterialReport]]:
    catalog = load_catalog()
    all_sources, reports = [], []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        slug = catalog.get(_nfc(pdf.name), {}).get("slug") or slugify(pdf.name)
        try:
            pages, cached = ocr_pages(pdf, engine, cache_root / engine.name / slug, force)
        except OcrUnavailable as exc:
            reports.append(MaterialReport(pdf.name, slug, 0, 0, 0.0, 0, error=str(exc)))
            continue
        first_text = " ".join(b.text for b in pages[0]) if pages else ""
        material = describe(pdf, catalog, first_text)
        sources, page_reports = build_material(material, pages)
        confs = [s.ocr_confidence for s in sources if s.ocr_confidence is not None]
        reports.append(
            MaterialReport(
                file=pdf.name,
                slug=material.slug,
                pages=len(pages),
                fragments=len(sources),
                mean_confidence=round(sum(confs) / len(confs), 1) if confs else 0.0,
                cached_pages=cached,
                page_reports=page_reports,
            )
        )
        all_sources.extend(sources)
    return all_sources, reports


def report_to_dict(report: MaterialReport) -> dict:
    return asdict(report)
