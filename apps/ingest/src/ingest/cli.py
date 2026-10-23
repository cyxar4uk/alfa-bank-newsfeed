"""Командная строка: `ingest all` — новости и аналитика за один запуск.

Раскладка каталога данных (--data):
  raw/alfa_analytics/*.pdf          вход: аналитика банка (материалы кейса, не в git)
  raw/derived/alfa_fragments.jsonl  выход: фрагменты аналитики по схеме Source (для поиска)
  raw/derived/alfa_pages.jsonl      выход: страницы аналитики целиком (для дословной сверки цитат банка)
  raw/derived/ocr/<движок>/<slug>/pNNN.*  кэш распознавания по страницам (json) и текст для проверки (txt)
  raw/derived/news.jsonl            выход: новости по схеме Source
  raw/derived/report.json           что получилось: ленты, страницы, уверенность распознавания
  raw/derived/llm_calls.jsonl       журнал вызовов моделей: цель, модель, токены, стоимость
  demo/news_snapshot.jsonl          снимок новостей для работы без сети (в git)
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ingest.analytics.ocr import CacheOnlyEngine, OcrUnavailable, make_engine
from ingest.analytics.pipeline import VLM_ENGINE, process_folder, report_to_dict
from ingest.llm import LlmUnavailable
from ingest.models import Source
from ingest.news.fetch import load_feeds
from ingest.news.normalize import MSK
from ingest.news.pipeline import collect_news
from ingest.tagging.llm import make_llm_tagger


def write_jsonl(path: Path, items: list[Source]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(item.model_dump_json(exclude_none=True) + "\n")


def read_jsonl(path: Path) -> list[Source]:
    with path.open(encoding="utf-8") as f:
        return [Source.model_validate_json(line) for line in f if line.strip()]


def run_news(data: Path, llm_mode: str, snapshot: bool, feeds_path: str | None) -> dict:
    derived = data / "raw" / "derived"
    snapshot_path = data / "demo" / "news_snapshot.jsonl"
    try:
        llm = make_llm_tagger(llm_mode, derived)
    except LlmUnavailable as exc:
        print(f"  разметка моделью недоступна ({exc}) — размечаем только словарями")
        llm = None
    news, reports = collect_news(load_feeds(feeds_path), llm)
    for r in reports:
        status = f"{r.items} записей" if r.ok else f"ошибка: {r.error}"
        print(f"  {r.publisher:<14} {r.feed_id:<22} {status}")
    if getattr(llm, "failures", 0):
        print(f"  модель не ответила по {llm.failures} новостям — у них только разметка словарей")
    used_snapshot = False
    if not news and snapshot_path.exists():
        # сети нет — работаем на снимке, чтобы сервис не остался без новостей
        news = read_jsonl(snapshot_path)
        used_snapshot = True
        print(f"  ленты недоступны, взят снимок {snapshot_path} ({len(news)} новостей)")
    write_jsonl(derived / "news.jsonl", news)
    if snapshot and news and not used_snapshot:
        write_jsonl(snapshot_path, news)
        print(f"  снимок обновлён: {snapshot_path}")
    merged = sum(1 for n in news if n.also_reported_by)
    print(f"  новостей после склейки: {len(news)}, из них сюжетов из нескольких источников: {merged}")
    return {
        "feeds": [asdict(r) for r in reports],
        "news": len(news),
        "stories_with_duplicates": merged,
        "from_snapshot": used_snapshot,
    }


def run_analytics(data: Path, engine_name: str, force: bool, vlm: bool) -> dict:
    pdf_dir = data / "raw" / "alfa_analytics"
    derived = data / "raw" / "derived"
    journal = derived / "llm_calls.jsonl"
    if not pdf_dir.is_dir():
        print(f"  нет каталога {pdf_dir} — аналитику пропускаем")
        return {"skipped": f"нет каталога {pdf_dir}"}
    try:
        engine = make_engine(engine_name, journal)
    except OcrUnavailable as exc:
        # без движка собираем фрагменты из уже распознанных страниц
        print(f"  {exc}")
        print(f"  работаем по кэшу распознавания {derived / 'ocr'}")
        engine = CacheOnlyEngine(engine_name, str(exc))
    vlm_engine = None
    if vlm:
        try:
            vlm_engine = make_engine(VLM_ENGINE, journal)
        except OcrUnavailable as exc:
            print(f"  Qwen3-VL недоступен ({exc}) — берём его страницы из кэша")
    result = process_folder(pdf_dir, derived / "ocr", engine, force, vlm_engine)
    write_jsonl(derived / "alfa_fragments.jsonl", result.fragments)
    write_jsonl(derived / "alfa_pages.jsonl", result.pages)
    for r in result.reports:
        if r.missing_pages:
            pages = ", ".join(map(str, r.missing_pages))
            print(f"  {r.slug:<24} не распознаны стр. {pages}: {r.errors[0] if r.errors else 'причина неизвестна'}")
        if r.missing_pages and len(r.missing_pages) == r.pages:
            continue
        print(
            f"  {r.slug:<24} стр. {r.pages:>2} · фрагментов {r.fragments:>3} · уверенность {r.mean_confidence:>5}"
            f" · из кэша {r.cached_pages} · Qwen3-VL стр. {r.vlm_pages}"
        )
    print(f"  всего фрагментов: {len(result.fragments)}, страниц: {len(result.pages)}")
    return {
        "engine": engine.name,
        "fragments": len(result.fragments),
        "pages": len(result.pages),
        "materials": [report_to_dict(r) for r in result.reports],
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ingest", description="Сбор новостей и аналитики Альфа-Банка")
    parser.add_argument("command", choices=["all", "news", "analytics"])
    parser.add_argument("--data", type=Path, default=Path("data"), help="каталог данных (по умолчанию ./data)")
    parser.add_argument("--engine", default="tesseract", help="основное распознавание: tesseract | qwen3-vl-mock")
    parser.add_argument(
        "--vlm", action="store_true", help="распознать недостающие страницы Qwen3-VL (платно, нужен ключ)"
    )
    parser.add_argument("--llm", default="off", help="разметка новостей моделью поверх словарей: off | mock | api")
    parser.add_argument("--feeds", default=None, help="свой файл лент вместо встроенного sources.toml")
    parser.add_argument("--snapshot", action="store_true", help="перезаписать data/demo/news_snapshot.jsonl")
    parser.add_argument("--force", action="store_true", help="распознать заново, не глядя в кэш")
    args = parser.parse_args(argv)

    out = args.data / "raw" / "derived" / "report.json"
    report: dict = json.loads(out.read_text("utf-8")) if out.exists() else {}
    report["started_at"] = datetime.now(MSK).isoformat(timespec="seconds")
    if args.command in ("all", "news"):
        print("Новости:")
        report["news"] = run_news(args.data, args.llm, args.snapshot, args.feeds)
    if args.command in ("all", "analytics"):
        print("Аналитика банка:")
        report["analytics"] = run_analytics(args.data, args.engine, args.force, args.vlm)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
