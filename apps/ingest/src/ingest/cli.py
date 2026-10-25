"""Командная строка: `ingest all` — новости и аналитика за один запуск; `ingest load` — загрузить готовое в БД;
`ingest serve` — загрузить и дальше обновлять новости по расписанию (сервис в compose); `ingest classify` — спросить
модель о новостях, которые словари не отнесли ни к деловым, ни к прочим.

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
import os
import sys
import time
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


DEFAULT_DATABASE_URL = "postgresql://newsfeed:newsfeed@127.0.0.1:5433/newsfeed"


def connect_db(url: str, attempts: int = 30, delay: float = 2.0):
    """Подключиться к БД, дождавшись её (в compose она может подняться позже)."""
    import psycopg

    for attempt in range(1, attempts + 1):
        try:
            return psycopg.connect(url, autocommit=True)
        except psycopg.OperationalError:
            if attempt == attempts:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")


# столько новостей за круг дозаполняем картинкой и полным текстом со страниц материалов
MEDIA_BATCH = 200


def run_load(data: Path, url: str, media_limit: int = MEDIA_BATCH) -> dict:
    from ingest.db.load import load_all

    with connect_db(url) as conn:
        result = load_all(conn, data, media_limit)
    _print_load(result)
    return result


def _print_load(result: dict) -> None:
    for name in ("snapshot", "news"):
        if name in result:
            s = result[name]
            print(
                f"  {name:<9} прочитано {s['read']:>4} · новых {s['inserted']:>4} · обновлено {s['updated']:>4}"
                f" · без изменений {s['unchanged']:>4} · дописано к событиям {s['merged']:>3}"
            )
    if m := result.get("media"):
        print(
            f"  страницы материалов: проверено {m['checked']} · картинок {m['images']} · полных текстов {m['texts']}"
            f" · убрано заглушек {m['placeholders']}"
        )
    if result.get("retagged"):
        print(f"  разметка: словари изменились — переразмечено новостей {result['retagged']}")
    a = result.get("analytics", {})
    if a.get("skipped"):
        print(f"  аналитика: пропущена — {a.get('reason')}")
    elif a:
        print(f"  аналитика: материалов {a['materials']}, страниц {a['pages']}, фрагментов {a['fragments']}")


def run_classify(conn, data: Path, limit: int = 200) -> dict | None:
    """Сомнительные «деловая или нет» — модели, если есть ключ (LLM_API_KEY, LLM_BASE_URL); без ключа — пропуск.

    Журнал вызовов — LLM_JOURNAL (в compose — общий том кэша), иначе raw/derived/llm_calls.jsonl; суточный бюджет
    отсева — INGEST_LLM_DAILY_BUDGET_RUB."""
    from ingest.llm import LlmClient
    from ingest.tagging.business import DEFAULT_BUDGET_RUB, classify_doubtful

    journal = Path(os.environ.get("LLM_JOURNAL") or data / "raw" / "derived" / "llm_calls.jsonl")
    try:
        llm = LlmClient.from_env(journal)
    except LlmUnavailable:
        return None
    try:
        budget = float(os.environ.get("INGEST_LLM_DAILY_BUDGET_RUB") or DEFAULT_BUDGET_RUB)
    except ValueError:
        budget = DEFAULT_BUDGET_RUB
    stats = classify_doubtful(conn, llm, limit, budget, journal)
    stopped = f" · остановлено: {stats.stopped}" if stats.stopped else ""
    print(
        f"  деловая или нет (модель): спрошено {stats.asked} · деловых {stats.business}"
        f" · не деловых {stats.not_business} · запросов {stats.calls}{stopped}"
    )
    return asdict(stats)


def run_serve(data: Path, url: str, every: float, iterations: int | None = None) -> None:
    """Загрузить снимок и готовые файлы, затем собирать новости из лент каждые `every` минут — сразу в БД.

    Файлы в `data` не пишутся (в compose том только на чтение): распознавание аналитики — отдельной командой
    `ingest analytics`, сервис берёт готовые `raw/derived/alfa_*.jsonl`. Нет сети — ленты не отвечают, в базе остаётся
    загруженное. Сбой БД — повтор на следующем круге. SIGTERM — штатная остановка (иначе процесс с PID 1 его не
    слышит и `docker compose stop` ждёт 10 секунд).
    """
    import signal

    import psycopg

    from ingest.db.load import enrich_news, load_news

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    loaded = False
    n = 0
    while True:
        n += 1
        if not loaded:  # снимок и аналитика — до первой удачной загрузки, повторяем каждый круг
            print("Загрузка в БД:")
            try:
                run_load(data, url)
                loaded = True
            except (psycopg.Error, OSError) as exc:
                print(f"  сбой: {exc} — повтор через {every:g} мин")
        print(f"Новости ({datetime.now(MSK):%d.%m %H:%M}):")
        try:
            news, reports = collect_news(load_feeds(None))
            for r in reports:
                status = f"{r.items} записей" if r.ok else f"ошибка: {r.error}"
                print(f"  {r.publisher:<14} {r.feed_id:<22} {status}")
            if news:
                with connect_db(url, attempts=3) as conn:
                    _print_load({"news": load_news(conn, news).__dict__})
                    try:
                        _print_load({"media": enrich_news(conn, MEDIA_BATCH).__dict__})
                    except psycopg.Error:
                        raise
                    except Exception as exc:  # noqa: BLE001 — картинки не должны останавливать сбор новостей
                        print(f"  страницы материалов: сбой {exc!r} — повтор на следующем круге")
                    run_classify(conn, data)
            else:
                print("  ленты не ответили — в базе остаётся загруженное")
        except (psycopg.Error, OSError) as exc:
            print(f"  сбой: {exc} — повтор через {every:g} мин")
        if iterations is not None and n >= iterations:
            return
        time.sleep(every * 60)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ingest", description="Сбор новостей и аналитики Альфа-Банка")
    parser.add_argument("command", choices=["all", "news", "analytics", "load", "serve", "classify"])
    parser.add_argument("--data", type=Path, default=Path("data"), help="каталог данных (по умолчанию ./data)")
    parser.add_argument("--engine", default="tesseract", help="основное распознавание: tesseract | qwen3-vl-mock")
    parser.add_argument(
        "--vlm", action="store_true", help="распознать недостающие страницы Qwen3-VL (платно, нужен ключ)"
    )
    parser.add_argument("--llm", default="off", help="разметка новостей моделью поверх словарей: off | mock | api")
    parser.add_argument("--feeds", default=None, help="свой файл лент вместо встроенного sources.toml")
    parser.add_argument("--snapshot", action="store_true", help="перезаписать data/demo/news_snapshot.jsonl")
    parser.add_argument("--force", action="store_true", help="распознать заново, не глядя в кэш")
    parser.add_argument(
        "--every", type=float, default=float(os.environ.get("INGEST_EVERY_MIN", "30")), help="serve: период сбора, мин"
    )
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if args.command == "load":
        print("Загрузка в БД:")
        run_load(args.data, url)
        return 0
    if args.command == "classify":
        with connect_db(url) as conn:
            if run_classify(conn, args.data) is None:
                print("нет LLM_API_KEY и LLM_BASE_URL — сомнительные новости остаются в ленте")
        return 0
    if args.command == "serve":
        if args.every < 1:
            parser.error("--every: не меньше 1 минуты — ленты не нужно опрашивать чаще")
        run_serve(args.data, url, args.every)
        return 0

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
