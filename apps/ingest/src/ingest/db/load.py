"""Загрузка материалов в PostgreSQL: новости (снимок, свежий сбор) и аналитика банка (страницы и фрагменты).

Повторная загрузка не плодит дубли:
- новость с тем же id обновляется, только если поменялась (разметка, лид); упоминания у других издателей сливаются;
- новость, которой нет в базе, но сюжет которой уже есть (те же правила склейки, что у парсера, окно 48 часов),
  не заводит второе событие — она дописывается в `also_reported_by` уже загруженного. id события не меняется:
  на него ссылаются кэш инсайтов и карточки;
- новости не удаляются: ленты отдают только последние записи, история копится в базе;
- аналитика — целый набор: неизменившиеся файлы пропускаются, изменившиеся заменяют набор в одной транзакции.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from ingest.db.schema import ensure_schema
from ingest.models import Mention, Source
from ingest.news.dedup import TIME_WINDOW, similar_titles
from ingest.news.media import Fetcher
from ingest.news.normalize import news_id
from ingest.text import proper_names, stems

SNAPSHOT = Path("demo") / "news_snapshot.jsonl"
DERIVED = Path("raw") / "derived"


@dataclass
class NewsStats:
    read: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    merged: int = 0  # дописаны упоминанием к уже загруженному событию


@dataclass
class AnalyticsStats:
    materials: int = 0
    pages: int = 0
    fragments: int = 0
    skipped: bool = False  # файлы не менялись с прошлой загрузки
    reason: str | None = None


@dataclass
class _Event:
    """Загруженное событие — кандидат на склейку с новой записью."""

    id: str
    title: str
    url: str | None
    published_at: object
    mentions: list[dict]
    stems: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)


def content_hash(item: Source) -> str:
    data = item.model_dump(
        mode="json", include={"title", "publisher", "url", "published_at", "fragment", "reliability"}
    )
    data["tags"] = item.tags.model_dump(mode="json")
    data["expectations"] = [e.model_dump(mode="json") for e in item.expectations]
    return hashlib.sha1(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _mention(item: Source) -> dict:
    return Mention(
        publisher=item.publisher, title=item.title, url=item.url or "", published_at=item.published_at
    ).model_dump(mode="json")


def _merge_mentions(
    current: list[dict], new: Iterable[dict], own_url: str | None, own_rows: set[str] = frozenset()
) -> list[dict]:
    """Добавить упоминания без повторов. Упоминание, у которого в базе своя строка-событие, не дописываем:
    иначе сюжет был бы в базе дважды — и событием, и упоминанием."""
    out, seen = list(current), {m["url"] for m in current}
    for m in new:
        url = m["url"]
        if url and url != own_url and url not in seen and news_id(url) not in own_rows:
            seen.add(url)
            out.append(m)
    return out


def _row(item: Source, origin: str) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "publisher": item.publisher,
        "reliability": item.reliability,
        "url": item.url,
        "published_at": item.published_at,
        "fragment": item.fragment,
        "image_url": item.image_url,
        "source_icon_url": item.source_icon_url,
        "body": item.text,
        "tags": Jsonb(item.tags.model_dump(mode="json")),
        "factors": [f.code for f in item.tags.factors],
        "okved": item.tags.okved,
        "expectations": Jsonb([e.model_dump(mode="json") for e in item.expectations]),
        "also_reported_by": Jsonb([m.model_dump(mode="json") for m in item.also_reported_by]),
        "origin": origin,
        "content_hash": content_hash(item),
    }


_INSERT = """
INSERT INTO news (id, title, publisher, url, published_at, fragment, tags, factors, okved, expectations,
                  also_reported_by, origin, content_hash, body, reliability, image_url, source_icon_url)
VALUES (%(id)s, %(title)s, %(publisher)s, %(url)s, %(published_at)s, %(fragment)s, %(tags)s, %(factors)s, %(okved)s,
        %(expectations)s, %(also_reported_by)s, %(origin)s, %(content_hash)s, %(body)s, %(reliability)s,
        %(image_url)s, %(source_icon_url)s)
"""

_UPDATE = """
UPDATE news SET title = %(title)s, publisher = %(publisher)s, reliability = %(reliability)s, url = %(url)s,
    published_at = %(published_at)s,
    fragment = %(fragment)s, tags = %(tags)s, factors = %(factors)s, okved = %(okved)s,
    expectations = %(expectations)s, also_reported_by = %(also_reported_by)s, content_hash = %(content_hash)s,
    -- картинку и текст со страницы (enrich_news) запись из ленты без них не стирает
    image_url = COALESCE(%(image_url)s, image_url), source_icon_url = COALESCE(%(source_icon_url)s, source_icon_url),
    -- присланная на разбор новость, ставшая событием ленты, не сохраняет текст пользователя: полный текст у ленты —
    -- только где его разрешают условия издателя
    body = CASE WHEN origin = 'user' AND %(origin)s = 'feed' THEN %(body)s ELSE COALESCE(%(body)s, body) END,
    origin = CASE WHEN %(origin)s = 'feed' THEN 'feed' ELSE origin END, updated_at = now()
WHERE id = %(id)s
"""


def _events_near(conn: psycopg.Connection, items: list[Source]) -> list[_Event]:
    dates = [i.published_at for i in items if i.published_at is not None]
    if dates:
        rows = conn.execute(
            """
            SELECT id, title, url, published_at, also_reported_by FROM news
            WHERE origin = 'feed' AND (published_at IS NULL OR published_at BETWEEN %s AND %s)
            """,
            (min(dates) - TIME_WINDOW, max(dates) + TIME_WINDOW),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, url, published_at, also_reported_by FROM news WHERE origin = 'feed'"
        ).fetchall()
    return [_event(*r) for r in rows]


def _event(id_: str, title: str, url: str | None, published_at, mentions: list[dict]) -> _Event:
    return _Event(id_, title, url, published_at, list(mentions), stems(title), proper_names(title))


def _close(a, b) -> bool:
    return a is None or b is None or abs(a - b) <= TIME_WINDOW


def _order(e: _Event) -> tuple:
    return (e.published_at is None, e.published_at.timestamp() if e.published_at else 0.0, e.id)


def load_news(
    conn: psycopg.Connection, items: Iterable[Source], origin: str = "feed", update_existing: bool = True
) -> NewsStats:
    """Загрузить новости. Вызывать вне открытой транзакции: загрузка — одна транзакция целиком.

    update_existing=False — только добавлять (снимок: его старые версии не должны откатывать свежий сбор).
    """
    items = [i for i in items if i.kind == "news"]
    stats = NewsStats(read=len(items))
    if not items:
        return stats
    with conn.transaction():
        # два загрузчика (и сохранение присланной новости) одновременно склеили бы один сюжет в два события
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_news_load'))")
        ids = [i.id for i in items]
        existing = {
            r[0]: (r[1], list(r[2]), r[3])
            for r in conn.execute(
                "SELECT id, content_hash, also_reported_by, origin FROM news WHERE id = ANY(%s)", (ids,)
            )
        }
        # картинка, значок и полный текст в отпечаток не входят (картинку и текст дописывает и enrich_news), поэтому
        # запись, которая принесла их туда, где в базе пусто, обновляем даже с тем же отпечатком
        gaps = {
            r[0]: r[1:]
            for r in conn.execute(
                "SELECT id, image_url IS NULL, source_icon_url IS NULL, body IS NULL FROM news WHERE id = ANY(%s)",
                (ids,),
            )
        }
        # заглушки сайтов, найденные enrich_news: из ленты их не берём, иначе картинка возвращалась бы каждый круг
        stubs = set(conn.execute("SELECT publisher, image_url FROM news_image_stubs").fetchall())
        # своя строка-событие — только из лент: присланная пользователем новость может стать упоминанием
        mention_ids = [news_id(m.url) for i in items for m in i.also_reported_by if m.url]
        own_rows = {
            r[0] for r in conn.execute("SELECT id FROM news WHERE id = ANY(%s) AND origin = 'feed'", (mention_ids,))
        }
        own_rows |= {i for i, (_, _, o) in existing.items() if o == "feed"}
        events = _events_near(conn, items)
        by_id = {e.id: e for e in events}
        index: dict[str, list[_Event]] = defaultdict(list)
        mentioned: dict[str, _Event] = {}
        for e in events:
            for s in e.stems:
                index[s].append(e)
            for m in e.mentions:
                mentioned[m["url"]] = e

        for item in items:
            if (item.publisher, item.image_url) in stubs:
                item = item.model_copy(update={"image_url": None})
            row = _row(item, origin)
            new_mentions = [m.model_dump(mode="json") for m in item.also_reported_by]
            known = existing.get(item.id)
            # присланная на разбор новость пришла из ленты: если её сюжет уже есть — она упоминание, а не событие
            if known is not None and not (known[2] == "user" and origin == "feed"):
                if not update_existing:
                    stats.unchanged += 1
                    continue
                old_hash, old_mentions, old_origin = known
                mentions = _merge_mentions(old_mentions, new_mentions, item.url, own_rows)
                no_image, no_icon, no_body = gaps.get(item.id, (False, False, False))
                fills_gap = (
                    (no_image and item.image_url) or (no_icon and item.source_icon_url) or (no_body and item.text)
                )
                if (
                    old_hash == row["content_hash"]
                    and mentions == old_mentions
                    and old_origin == origin
                    and not fills_gap
                ):
                    stats.unchanged += 1
                    continue
                row["also_reported_by"] = Jsonb(mentions)
                conn.execute(_UPDATE, row)
                existing[item.id] = (row["content_hash"], mentions, old_origin)
                gaps.pop(item.id, None)
                if item.id in by_id:
                    by_id[item.id].mentions = mentions
                stats.updated += 1
                continue

            head = mentioned.get(item.url or "")
            if head is None and origin == "feed":
                st, names = stems(item.title), proper_names(item.title)
                candidates = sorted({e.id: e for s in st for e in index[s]}.values(), key=_order)
                for cand in candidates:
                    if similar_titles(cand.stems, st, cand.names, names) and _close(
                        cand.published_at, item.published_at
                    ):
                        head = cand
                        break
            if head is not None and head.id != item.id:
                mentions = _merge_mentions(head.mentions, [_mention(item), *new_mentions], head.url, own_rows)
                if mentions != head.mentions:
                    conn.execute(
                        "UPDATE news SET also_reported_by = %s, updated_at = now() WHERE id = %s",
                        (Jsonb(mentions), head.id),
                    )
                    head.mentions = mentions
                for m in mentions:
                    mentioned[m["url"]] = head
                stats.merged += 1
                continue

            mentions = _merge_mentions(known[1] if known else [], new_mentions, item.url, own_rows)
            row["also_reported_by"] = Jsonb(mentions)
            if known is not None:  # присланная пользователем, сюжета в базе нет — становится событием ленты
                conn.execute(_UPDATE, row)
                stats.updated += 1
            else:
                conn.execute(_INSERT, row)
                stats.inserted += 1
            existing[item.id] = (row["content_hash"], mentions, origin)
            gaps.pop(item.id, None)
            own_rows.add(item.id)
            if origin == "feed":
                event = _event(item.id, item.title, item.url, item.published_at, mentions)
                by_id[item.id] = event
                for s in event.stems:
                    index[s].append(event)
                for m in event.mentions:
                    mentioned[m["url"]] = event
    return stats


def save_user_news(conn: psycopg.Connection, item: Source, body: str | None) -> bool:
    """Сохранить новость, присланную на разбор. Уже загруженную не трогает. True — запись новая."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_news_load'))")
        cur = conn.execute(_INSERT + " ON CONFLICT (id) DO NOTHING", {**_row(item, "user"), "body": body})
        return cur.rowcount == 1


# --- Аналитика банка ------------------------------------------------------------------------------


def _signature(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()


def load_analytics(
    conn: psycopg.Connection, pages: list[Source], fragments: list[Source], signature: str | None = None
) -> AnalyticsStats:
    """Заменить набор аналитики целиком. signature — отпечаток файлов: совпал с загруженным — ничего не делаем."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_alfa_load'))")
        if signature is not None:
            row = conn.execute("SELECT signature FROM search_loads WHERE name = 'alfa'").fetchone()
            if row and row[0] == signature:
                return AnalyticsStats(skipped=True, reason="файлы не менялись")
        materials: dict[str, dict] = {}
        for p in pages:
            mid = p.id.split("#", 1)[0]
            m = materials.setdefault(
                mid,
                {
                    "id": mid,
                    "title": p.title,
                    "publisher": p.publisher,
                    "file": p.file,
                    "published_at": p.published_at,
                    "pages": 0,
                    "stale": bool(p.stale),
                },
            )
            m["pages"] += 1
        page_ids = {p.id for p in pages}
        # фрагмент без своей страницы сверить с текстом нельзя — такой в поиск не берём
        kept = [f for f in fragments if (f.page_ref or f.id.rsplit("-", 1)[0]) in page_ids]

        conn.execute("DELETE FROM alfa_materials")  # страницы и фрагменты удаляются каскадом
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO alfa_materials (id, title, publisher, file, published_at, pages, stale)
                VALUES (%(id)s, %(title)s, %(publisher)s, %(file)s, %(published_at)s, %(pages)s, %(stale)s)
                """,
                list(materials.values()),
            )
            cur.executemany(
                "INSERT INTO alfa_pages (id, material, page, ocr_text, vlm_text) VALUES (%s, %s, %s, %s, %s)",
                [(p.id, p.id.split("#", 1)[0], p.page or 0, p.fragment, p.vlm_text) for p in pages],
            )
            cur.executemany(
                """
                INSERT INTO alfa_fragments (id, material, page_id, page, fragment, ocr_engine, ocr_confidence, tags,
                                            factors, title)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        f.id,
                        f.id.split("#", 1)[0],
                        f.page_ref or f.id.rsplit("-", 1)[0],
                        f.page or 0,
                        f.fragment,
                        f.ocr_engine,
                        f.ocr_confidence,
                        Jsonb(f.tags.model_dump(mode="json")),
                        [x.code for x in f.tags.factors],
                        f.title,
                    )
                    for f in kept
                ],
            )
        if signature is not None:
            conn.execute(
                """
                INSERT INTO search_loads (name, signature, rows) VALUES ('alfa', %s, %s)
                ON CONFLICT (name) DO UPDATE SET signature = EXCLUDED.signature, rows = EXCLUDED.rows, loaded_at = now()
                """,
                (signature, len(kept)),
            )
    return AnalyticsStats(materials=len(materials), pages=len(pages), fragments=len(kept))


# --- Каталог данных целиком -----------------------------------------------------------------------


def read_jsonl(path: Path) -> list[Source]:
    """Строки, которые не разбираются по схеме, пропускаются: одна битая запись не должна останавливать загрузку."""
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                out.append(Source.model_validate_json(line))
            except ValueError:
                continue
    return out


def load_analytics_files(conn: psycopg.Connection, data: Path) -> AnalyticsStats:
    pages_path, fragments_path = data / DERIVED / "alfa_pages.jsonl", data / DERIVED / "alfa_fragments.jsonl"
    if not (pages_path.exists() and fragments_path.exists()):
        return AnalyticsStats(skipped=True, reason=f"нет {pages_path.name} и {fragments_path.name} в {data / DERIVED}")
    return load_analytics(
        conn, read_jsonl(pages_path), read_jsonl(fragments_path), signature=_signature(pages_path, fragments_path)
    )


def tagging_signature() -> str:
    """Отпечаток словарей и правил разметки и ожиданий: поменялись — новости в базе нужно разметить заново.

    Переводы строк приводятся к LF: иначе копия на Windows и образ в Docker давали бы разные отпечатки."""
    from importlib import resources

    h = hashlib.sha256()
    for package, name in (
        ("ingest.tagging", "dictionaries.toml"),
        ("ingest.tagging", "rules.py"),
        ("ingest.news", "expectations.py"),
        ("ingest.news", "pipeline.py"),
    ):
        h.update(resources.files(package).joinpath(name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def retag_news(conn: psycopg.Connection) -> int:
    """Разметить заново новости в базе, если словари или правила поменялись с прошлой разметки.

    Без этого исправление словаря не дошло бы до новостей, которых уже нет в лентах: загрузчик обновляет только то,
    что пришло снова, а снимок лишь добавляет. Размеченные моделью (`tagged_by` с `llm`) не трогаем — их разметку
    правила не повторят. Возвращает, сколько новостей поменялось.
    """
    from ingest.news.normalize import MSK
    from ingest.news.pipeline import tag_source

    signature = tagging_signature()
    changed = 0
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_news_load'))")
        row = conn.execute("SELECT signature FROM search_loads WHERE name = 'tagging'").fetchone()
        if row and row[0] == signature:
            return 0
        rows = conn.execute(
            "SELECT id, title, publisher, url, published_at, fragment, tags, content_hash, reliability FROM news"
        ).fetchall()
        for id_, title, publisher, url, published_at, fragment, tags, old_hash, reliability in rows:
            if "llm" in (tags or {}).get("tagged_by", []):
                continue
            src = tag_source(
                Source(
                    id=id_, kind="news", title=title, publisher=publisher or "", reliability=reliability, url=url,
                    published_at=published_at.astimezone(MSK) if published_at else None, fragment=fragment,
                )
            )  # fmt: skip
            new_hash = content_hash(src)
            if new_hash == old_hash:
                continue
            conn.execute(
                """
                UPDATE news SET tags = %s, factors = %s, okved = %s, expectations = %s, content_hash = %s,
                       updated_at = now()
                WHERE id = %s
                """,
                (
                    Jsonb(src.tags.model_dump(mode="json")),
                    [f.code for f in src.tags.factors],
                    src.tags.okved,
                    Jsonb([e.model_dump(mode="json") for e in src.expectations]),
                    new_hash,
                    id_,
                ),
            )
            changed += 1
        conn.execute(
            """
            INSERT INTO search_loads (name, signature, rows) VALUES ('tagging', %s, %s)
            ON CONFLICT (name) DO UPDATE SET signature = EXCLUDED.signature, rows = EXCLUDED.rows, loaded_at = now()
            """,
            (signature, changed),
        )
    return changed


def backfill_reliability(conn: psycopg.Connection) -> int:
    """Проставить надёжность новостям из лент, загруженным до её появления: по издателю — уровень его ленты.

    Снимок только добавляет записи, а новости, которых уже нет в лентах, иначе остались бы без уровня."""
    from ingest.news.fetch import load_feeds

    tiers: dict[str, str] = {}
    for feed in load_feeds():
        tiers.setdefault(feed.publisher, feed.reliability)
    with conn.transaction():
        cur = conn.execute(
            """
            UPDATE news SET reliability = t.reliability
            FROM jsonb_each_text(%s::jsonb) AS t(publisher, reliability)
            WHERE news.publisher = t.publisher AND news.reliability IS NULL AND news.origin = 'feed'
            """,
            (Jsonb(tiers),),
        )
        return cur.rowcount


def backfill_icons(conn: psycopg.Connection) -> int:
    """Значок издания новостям из лент, у которых его нет (загружены раньше или из снимка): по издателю."""
    from ingest.news.fetch import load_feeds

    icons: dict[str, str] = {}
    for feed in load_feeds():
        if feed.icon:
            icons.setdefault(feed.publisher, feed.icon)
    with conn.transaction():
        cur = conn.execute(
            """
            UPDATE news SET source_icon_url = t.icon
            FROM jsonb_each_text(%s::jsonb) AS t(publisher, icon)
            WHERE news.publisher = t.publisher AND news.source_icon_url IS NULL AND news.origin = 'feed'
            """,
            (Jsonb(icons),),
        )
        return cur.rowcount


# одна и та же картинка у стольких новостей издателя — это заглушка сайта, а не иллюстрация материала
SHARED_IMAGE_MIN = 3
# столько кругов подряд страница не отвечала — больше не спрашиваем
MEDIA_ATTEMPTS = 3


@dataclass
class MediaStats:
    checked: int = 0
    images: int = 0
    texts: int = 0
    placeholders: int = 0  # убрано картинок-заглушек


def enrich_news(conn: psycopg.Connection, limit: int = 200, fetch: Fetcher | None = None) -> MediaStats:
    """Дозаполнить картинку и полный текст со страниц материалов: свежие новости из лент, которые ещё не проверяли.

    Страницу запрашиваем, только если у новости нет картинки или если лента разрешает полный текст (`full_text =
    "page"`) и его ещё нет; только у включённых лент — выключенные выключены в том числе из-за условий издателя.
    Страница не ответила — новость остаётся непроверенной до следующего круга (не больше MEDIA_ATTEMPTS раз).
    Сеть — вне транзакции.
    """
    from ingest.news.fetch import load_feeds
    from ingest.news.media import PageJob, fetch_pages

    fetch = fetch or fetch_pages
    feeds = {}
    for feed in load_feeds():
        if feed.enabled:
            feeds.setdefault(feed.publisher, feed)
    rows = conn.execute(
        """
        SELECT id, url, publisher, image_url IS NULL, body IS NULL FROM news
        WHERE origin = 'feed' AND media_checked_at IS NULL AND url IS NOT NULL AND publisher = ANY(%s)
        ORDER BY published_at DESC NULLS LAST LIMIT %s
        """,
        (list(feeds), limit),
    ).fetchall()
    jobs, nothing_to_fetch, need_image = [], [], set()
    for id_, url, publisher, no_image, no_body in rows:
        feed = feeds[publisher]
        want_text = feed.full_text == "page" and no_body
        if no_image:
            need_image.add(id_)
        if no_image or want_text:
            jobs.append(PageJob(id_, url, want_text, feed.text_container))
        else:
            nothing_to_fetch.append(id_)
    got = fetch(jobs) if jobs else {}
    stats = MediaStats(checked=len(nothing_to_fetch) + len(got))
    # не ответили — попытка засчитывается, только если сеть вообще есть (хоть одна страница ответила): сайт, который
    # недоступен постоянно, после MEDIA_ATTEMPTS кругов помечается проверенным и не занимает место в пачке
    failed = [j.id for j in jobs if j.id not in got] if got else []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_news_load'))")
        conn.execute("UPDATE news SET media_checked_at = now() WHERE id = ANY(%s)", (nothing_to_fetch,))
        conn.execute(
            """
            UPDATE news SET media_attempts = media_attempts + 1,
                   media_checked_at = CASE WHEN media_attempts + 1 >= %s THEN now() END
            WHERE id = ANY(%s)
            """,
            (MEDIA_ATTEMPTS, failed),
        )
        for id_, media in got.items():
            # пока страницу запрашивали, загрузчик мог записать картинку из ленты — её не перетираем
            conn.execute(
                """
                UPDATE news SET image_url = COALESCE(image_url, %s), body = COALESCE(body, %s),
                       media_checked_at = now()
                WHERE id = %s
                """,
                (media.image, media.text, id_),
            )
            stats.images += bool(media.image and id_ in need_image)
            stats.texts += bool(media.text)
        # заглушку запоминаем: загрузчик больше не возьмёт её из ленты и для свежих новостей
        conn.execute(
            """
            INSERT INTO news_image_stubs (publisher, image_url)
            SELECT publisher, image_url FROM news WHERE image_url IS NOT NULL AND publisher IS NOT NULL
            GROUP BY publisher, image_url HAVING count(*) >= %s
            ON CONFLICT DO NOTHING
            """,
            (SHARED_IMAGE_MIN,),
        )
        stats.placeholders = conn.execute(
            """
            UPDATE news SET image_url = NULL FROM news_image_stubs s
            WHERE news.origin = 'feed' AND news.publisher = s.publisher AND news.image_url = s.image_url
            """
        ).rowcount
    return stats


def clear_disallowed_text(conn: psycopg.Connection) -> int:
    """Убрать полный текст у новостей из лент издателей, у которых full_text больше не разрешён в sources.toml."""
    from ingest.news.fetch import load_feeds

    allowed = sorted({f.publisher for f in load_feeds() if f.full_text})
    with conn.transaction():
        return conn.execute(
            "UPDATE news SET body = NULL WHERE origin = 'feed' AND body IS NOT NULL AND NOT (publisher = ANY(%s))",
            (allowed,),
        ).rowcount


def recheck_new_text_sources(conn: psycopg.Connection) -> int:
    """Новостям лент, которым разрешили полный текст со страницы (`full_text = "page"`), вернуть очередь дозаполнения.
    Отпечаток — по каждому издателю (условия и контейнер текста): сбрасываем только тех, у кого он поменялся, и не
    трогаем попытки остальных. Возвращает, сколько новостей вернули в очередь."""
    from ingest.news.fetch import load_feeds

    page = {
        f.publisher: f"{f.full_text}:{f.text_container}" for f in load_feeds() if f.full_text == "page" and f.enabled
    }
    prints = {p: hashlib.sha256(v.encode("utf-8")).hexdigest() for p, v in page.items()}
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_news_load'))")
        stored = dict(conn.execute("SELECT name, signature FROM search_loads WHERE name LIKE 'page_text:%'").fetchall())
        changed_publishers = [p for p, digest in prints.items() if stored.get(f"page_text:{p}") != digest]
        if not changed_publishers:
            return 0
        changed = conn.execute(
            """
            UPDATE news SET media_checked_at = NULL, media_attempts = 0
            WHERE origin = 'feed' AND body IS NULL AND media_checked_at IS NOT NULL AND publisher = ANY(%s)
            """,
            (changed_publishers,),
        ).rowcount
        for publisher, digest in prints.items():
            conn.execute(
                """
                INSERT INTO search_loads (name, signature, rows) VALUES (%s, %s, 0)
                ON CONFLICT (name) DO UPDATE SET signature = EXCLUDED.signature, loaded_at = now()
                """,
                (f"page_text:{publisher}", digest),
            )
    return changed


def load_all(conn: psycopg.Connection, data: Path, media_limit: int = 0) -> dict:
    """Снимок новостей, свежий сбор (raw/derived/news.jsonl) и аналитика — в таком порядке; затем новости в базе
    размечаются заново, если словари или правила поменялись. media_limit > 0 — дозаполнить картинки и полный
    текст стольких новостей со страниц материалов (нужна сеть)."""
    ensure_schema(conn, migrate=True)
    result: dict = {}
    # снимок только добавляет: если запись уже есть, в базе версия свежее
    sources = (("snapshot", data / SNAPSHOT, False), ("news", data / DERIVED / "news.jsonl", True))
    for name, path, update in sources:
        if path.exists():
            result[name] = asdict(load_news(conn, read_jsonl(path), update_existing=update))
    result["analytics"] = asdict(load_analytics_files(conn, data))
    result["reliability"] = backfill_reliability(conn)
    result["icons"] = backfill_icons(conn)
    result["text_cleared"] = clear_disallowed_text(conn)
    result["text_recheck"] = recheck_new_text_sources(conn)
    result["retagged"] = retag_news(conn)
    if media_limit > 0:
        result["media"] = asdict(enrich_news(conn, media_limit))
    return result
