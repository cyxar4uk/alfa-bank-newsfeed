"""Аналитика банка: PDF-сканы → картинки страниц → распознавание (с кэшем) → страницы целиком и фрагменты Source."""

import hashlib
import json
import os
import re
import tomllib
import unicodedata
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from importlib import resources
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from ingest.analytics.fragments import HEADING_MAX_CHARS, Fragment, PageReport, clean_table, page_fragments
from ingest.analytics.ocr import OcrBlock, OcrEngine, OcrUnavailable
from ingest.models import Source, Tags
from ingest.news.normalize import MSK
from ingest.tagging.rules import tag
from ingest.text import stems

PUBLISHER = "Альфа-Банк"
# длинная сторона страницы ≈ 3500 px — это 300 dpi для A4
RENDER_LONG_SIDE = 3500
VLM_ENGINE = "qwen3-vl"
# фрагмент Tesseract с такой уверенностью считаем надёжным: новое содержание Qwen ищем только среди того, чего в нём нет
TRUSTED_CONFIDENCE = 85.0
# ниже этой уверенности фрагмент Tesseract испорчен (текст перемешан с графиком) и заменяется версией Qwen;
# между ним и TRUSTED_CONFIDENCE остаётся Tesseract — он дословнее, Qwen местами пересказывает
REPLACE_BELOW = 70.0
# фрагмент Qwen — новое содержание, если меньше половины его слов уже есть у Tesseract
NEW_CONTENT_MAX_COVERED = 0.5
# испорченный фрагмент Tesseract заменяется, если половина его слов есть во фрагменте Qwen
REPLACED_MIN_COVERED = 0.5
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
    stale: bool = False


@dataclass
class MaterialReport:
    file: str
    slug: str
    pages: int
    fragments: int
    mean_confidence: float
    cached_pages: int
    vlm_pages: int = 0
    missing_pages: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    page_reports: list[PageReport] = field(default_factory=list)


@dataclass
class OcrRun:
    pages: list[list[OcrBlock] | None]
    cached: int
    errors: list[str]


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def load_catalog() -> dict[str, dict]:
    raw = resources.files("ingest.analytics").joinpath("catalog.toml").read_text("utf-8")
    return {_nfc(k): v for k, v in tomllib.loads(raw).get("materials", {}).items()}


def slugify(name: str) -> str:
    """Латиница из имени файла плюс короткий хэш имени: у «Обзор.pdf» и «Прогноз.pdf» slug разный."""
    latin = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-") or "material"
    return f"{latin}-{hashlib.sha1(_nfc(name).encode('utf-8')).hexdigest()[:6]}"


def pdf_digest(pdf: Path) -> str:
    return hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]


def find_date(text: str, file_name: str) -> date | None:
    candidates = []
    m = _TEXT_DATE.search(text)
    if m:
        candidates.append((int(m.group(3)), _MONTHS.index(m.group(2).lower()) + 1, int(m.group(1))))
    m = _NAME_DATE.search(file_name)
    if m:
        candidates.append((int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for y, mo, d in candidates:
        try:
            return date(y, mo, d)
        except ValueError:  # «30 февраля» в распознанном тексте — пробуем следующий источник даты
            continue
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
            stale=bool(card.get("stale", False)),
        )
    return Material(file=pdf.name, slug=slugify(pdf.name), title=pdf.stem, date=find_date(first_page_text, pdf.name))


def render_page(page: pdfium.PdfPage) -> Image.Image:
    w, h = page.get_size()
    return page.render(scale=RENDER_LONG_SIDE / max(w, h), grayscale=True).to_pil()


def _cache_path(cache_dir: Path, page_no: int) -> Path:
    return cache_dir / f"p{page_no:03d}.json"


def _read_cache(path: Path, engine_name: str, digest: str | None) -> list[OcrBlock] | None:
    """Кэш годен, если распознан тем же движком и с того же PDF (новый выпуск под старым именем — заново)."""
    try:
        data = json.loads(path.read_text("utf-8"))
        if data.get("engine") != engine_name:
            return None
        if digest and data.get("pdf_sha") and data["pdf_sha"] != digest:
            return None
        return [OcrBlock(b["text"], float(b["confidence"]), tuple(b["bbox"])) for b in data["blocks"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None  # нет файла или он испорчен — страницу распознаём заново


def _write_cache(path: Path, pdf: Path, digest: str, page_no: int, engine: OcrEngine, blocks: list[OcrBlock]) -> None:
    payload = {
        "file": pdf.name,
        "pdf_sha": digest,
        "page": page_no,
        "engine": engine.name,
        "blocks": [b.to_dict() for b in blocks],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    path.with_suffix(".txt").write_text("\n\n".join(b.text for b in blocks), "utf-8")


def ocr_pages(pdf: Path, engine: OcrEngine, cache_dir: Path, force: bool = False, workers: int | None = None) -> OcrRun:
    """Распознаёт страницы, распознанные тем же движком берёт из кэша.

    Рендер идёт по очереди (pdfium не потокобезопасен), распознавание — параллельно, но в работе не больше
    2 × workers страниц: память не растёт с размером PDF. Первая же ошибка движка (нет ключа, бюджет, сеть,
    tesseract без языка) останавливает отправку новых страниц — не тратим деньги впустую; нераспознанные — None.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = pdf_digest(pdf)
    workers = workers or getattr(engine, "workers", None) or os.cpu_count() or 2
    cache_only = getattr(engine, "cache_only", False)
    doc = pdfium.PdfDocument(str(pdf))
    pages: list[list[OcrBlock] | None] = [None] * len(doc)
    cached, errors = 0, []
    pending: dict[Future, int] = {}

    def collect(done) -> None:
        for future in done:
            page_no = pending.pop(future)
            try:
                blocks = future.result()
            except OcrUnavailable as exc:
                errors.append(f"стр. {page_no}: {exc}")
                continue
            pages[page_no - 1] = blocks
            _write_cache(_cache_path(cache_dir, page_no), pdf, digest, page_no, engine, blocks)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(len(doc)):
                hit = None if force else _read_cache(_cache_path(cache_dir, i + 1), engine.name, digest)
                if hit is not None:
                    pages[i], cached = hit, cached + 1
                    continue
                if cache_only:
                    errors.append(f"стр. {i + 1}: {getattr(engine, 'reason', 'нет в кэше')}")
                    continue
                while len(pending) >= 2 * workers:
                    collect(wait(pending, return_when=FIRST_COMPLETED).done)
                if errors:
                    continue
                pending[pool.submit(engine.recognize, render_page(doc[i]))] = i + 1
            while pending:
                collect(wait(pending, return_when=FIRST_COMPLETED).done)
    finally:
        doc.close()
    return OcrRun(pages, cached, errors)


def cached_pages(
    cache_dir: Path, engine_name: str, count: int, digest: str | None = None
) -> list[list[OcrBlock] | None]:
    """Страницы второго движка только из кэша: чего нет — None, сеть не трогаем."""
    return [_read_cache(_cache_path(cache_dir, n), engine_name, digest) for n in range(1, count + 1)]


def _published(material: Material) -> datetime | None:
    d = material.date
    return datetime(d.year, d.month, d.day, tzinfo=MSK) if d else None


def page_text(blocks: list[OcrBlock]) -> str:
    """Текст страницы целиком в порядке чтения; строки-разделители таблиц убраны, как и во фрагментах."""
    return "\n\n".join(clean_table(b.text) for b in blocks)


def build_pages(
    material: Material,
    pages: list[list[OcrBlock] | None],
    vlm: list[list[OcrBlock] | None],
    engine_name: str = "tesseract",
) -> list[Source]:
    """Страница целиком — для дословной сверки цитат банка: fragment — основной движок, vlm_text — Qwen3-VL."""
    out = []
    for page_no, blocks in enumerate(pages, start=1):
        if blocks is None:
            continue
        vlm_blocks = vlm[page_no - 1] if page_no <= len(vlm) else None
        out.append(
            Source(
                id=f"src:alfa:{material.slug}#p{page_no}",
                kind="alfa_analytics",
                title=material.title,
                publisher=PUBLISHER,
                published_at=_published(material),
                fragment=page_text(blocks),
                vlm_text=page_text(vlm_blocks) if vlm_blocks else None,
                page=page_no,
                file=material.file,
                ocr_engine=engine_name,
                stale=material.stale or None,
            )
        )
    return out


def _covered(text: str, by: set[str]) -> float:
    """Какая доля значимых слов текста уже есть в другом тексте."""
    own = stems(text)
    return len(own & by) / len(own) if own else 1.0


def merge_page(
    page_no: int, blocks: list[OcrBlock], vlm_blocks: list[OcrBlock] | None, engine_name: str = "tesseract"
) -> tuple[list[tuple[Fragment, str]], PageReport]:
    """Фрагменты страницы: основа — основной движок (Tesseract дословнее), Qwen3-VL — для потерянного и испорченного.

    Фрагмент Qwen добавляется, если его слов почти нет в надёжных фрагментах основного движка (таблица, текст рядом с
    графиком). Испорченный фрагмент (уверенность ниже REPLACE_BELOW) заменяется фрагментом Qwen, который лучше всех
    его покрывает; если такого нет — остаётся как есть.
    """
    fragments, report = page_fragments(page_no, blocks)
    if not vlm_blocks:
        return [(f, engine_name) for f in fragments], report
    good = [f for f in fragments if f.confidence >= TRUSTED_CONFIDENCE]
    good_stems = set().union(*(stems(f.text) for f in good)) if good else set()
    vlm_fragments, _ = page_fragments(page_no, vlm_blocks, allow_tables=True)
    vlm_stems = [stems(f.text) for f in vlm_fragments]

    take = {i for i, f in enumerate(vlm_fragments) if _covered(f.text, good_stems) < NEW_CONTENT_MAX_COVERED}
    merged: list[tuple[Fragment, str]] = []
    for frag in fragments:
        if frag.confidence >= REPLACE_BELOW:
            merged.append((frag, engine_name))
            continue
        best, i = max(((_covered(frag.text, st), i) for i, st in enumerate(vlm_stems)), default=(0.0, -1))
        if best >= REPLACED_MIN_COVERED:
            take.add(i)
            report.replaced_by_vlm += 1
        else:
            merged.append((frag, engine_name))
    merged += [(vlm_fragments[i], VLM_ENGINE) for i in sorted(take)]
    report.added_from_vlm = len(take)
    report.kept = len(merged)
    return merged, report


def tag_fragment(text: str) -> Tags:
    """Заголовок фрагмента — первая строка, только если она короткая; иначе весь текст считается телом."""
    first, sep, rest = text.partition("\n")
    if sep and len(first) <= HEADING_MAX_CHARS:
        return tag(first, rest)
    return tag("", text)


def build_material(
    material: Material,
    pages: list[list[OcrBlock] | None],
    vlm: list[list[OcrBlock] | None] | None = None,
    engine_name: str = "tesseract",
) -> tuple[list[Source], list[PageReport]]:
    vlm = vlm or [None] * len(pages)
    sources, reports = [], []
    for page_no, blocks in enumerate(pages, start=1):
        if blocks is None:
            continue
        merged, report = merge_page(page_no, blocks, vlm[page_no - 1] if page_no <= len(vlm) else None, engine_name)
        reports.append(report)
        for n, (frag, engine) in enumerate(merged, start=1):
            sources.append(
                Source(
                    id=f"src:alfa:{material.slug}#p{page_no}-{n}",
                    kind="alfa_analytics",
                    title=material.title,
                    publisher=PUBLISHER,
                    published_at=_published(material),
                    fragment=frag.text,
                    tags=tag_fragment(frag.text),
                    page=page_no,
                    file=material.file,
                    page_ref=f"src:alfa:{material.slug}#p{page_no}",
                    ocr_engine=engine,
                    ocr_confidence=frag.confidence if engine != VLM_ENGINE else None,
                    stale=material.stale or None,
                )
            )
    return sources, reports


@dataclass
class AnalyticsResult:
    fragments: list[Source]
    pages: list[Source]
    reports: list[MaterialReport]


def process_folder(
    pdf_dir: Path, cache_root: Path, engine: OcrEngine, force: bool = False, vlm_engine: OcrEngine | None = None
) -> AnalyticsResult:
    """engine — основной движок (Tesseract). vlm_engine — распознать и Qwen3-VL; без него Qwen берётся из кэша."""
    catalog = load_catalog()
    result = AnalyticsResult([], [], [])
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        slug = catalog.get(_nfc(pdf.name), {}).get("slug") or slugify(pdf.name)
        run = ocr_pages(pdf, engine, cache_root / engine.name / slug, force)
        vlm_dir = cache_root / VLM_ENGINE / slug
        if vlm_engine is not None:
            vlm_run = ocr_pages(pdf, vlm_engine, vlm_dir, force)
            vlm, errors = vlm_run.pages, run.errors + vlm_run.errors
        else:
            vlm, errors = cached_pages(vlm_dir, VLM_ENGINE, len(run.pages), pdf_digest(pdf)), run.errors
        first = next((p for p in run.pages if p is not None), [])
        material = describe(pdf, catalog, " ".join(b.text for b in first))
        sources, page_reports = build_material(material, run.pages, vlm, engine.name)
        confs = [s.ocr_confidence for s in sources if s.ocr_confidence is not None]
        result.reports.append(
            MaterialReport(
                file=pdf.name,
                slug=material.slug,
                pages=len(run.pages),
                fragments=len(sources),
                mean_confidence=round(sum(confs) / len(confs), 1) if confs else 0.0,
                cached_pages=run.cached,
                vlm_pages=sum(p is not None for p in vlm),
                missing_pages=[n for n, p in enumerate(run.pages, start=1) if p is None],
                errors=errors[:5],
                page_reports=page_reports,
            )
        )
        result.fragments.extend(sources)
        result.pages.extend(build_pages(material, run.pages, vlm, engine.name))
    return result


def report_to_dict(report: MaterialReport) -> dict:
    return asdict(report)
