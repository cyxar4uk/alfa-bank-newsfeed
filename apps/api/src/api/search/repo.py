"""Поиск по новостям и аналитике банка — инструменты агента и данные для ленты.

Полнотекстовый поиск PostgreSQL с русской морфологией (snowball): «ставка», «ставки», «ставкой» — одно слово.
Запрос разбирается на основы слов, совпадением считается любая из них; порядок выдачи:

    score = 0,55 · покрытие + 0,25 · близость + 0,1 · свежесть + 0,1 · сила фактора        (новости)
    score = 0,6 · покрытие + 0,3 · близость + 0,1 · свежесть                              (аналитика)

покрытие — доля основ запроса, найденных в материале (все слова запроса важнее одного), близость —
`ts_rank_cd` (слова рядом и в заголовке — выше), свежесть — `exp(−возраст / 7 дней)` у новостей
и `exp(−возраст / 120 дней)` у аналитики (при равном совпадении берём свежий материал; без даты — 0), сила —
у новости по факторам из фильтра. Запрос без значимых слов («и в на», «???») ничего не находит.

Фрагмент аналитики в выдаче — не длиннее 600 знаков: у длинного — дословное окно вокруг найденных слов
(`ts_headline`), весь фрагмент — в `AlfaFragment.text`, который не сериализуется.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Any

from ingest.analytics.quotes import quote_in_page
from ingest.db.load import save_user_news
from ingest.db.schema import TS_CONFIG
from ingest.models import Source as IngestSource
from ingest.news.normalize import MSK, news_id
from ingest.tagging.rules import REGION_FACTOR, load_dictionaries
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.contract import Source, SourceTags
from api.okved import okved_prefix, sector_for
from api.search.models import PUBLIC_FRAGMENT_CHARS, AlfaFragment, NewsItem, NewsPage

MAX_LIMIT = 50
# цитата банка короче — не проверка: «12» или «а» найдутся на любой странице
MIN_QUOTE_CHARS, MIN_QUOTE_WORDS = 20, 3

# основы слов запроса и запрос «любое из слов»; кавычки и обратная косая в основе сломали бы разбор tsquery
_QUERY_CTE = f"""
lx AS (
    SELECT coalesce(array_agg(DISTINCT lexeme), '{{}}'::text[]) AS lex
    FROM unnest(to_tsvector('{TS_CONFIG}', translate(%(q)s, 'Ёё', 'Ее')))
    WHERE lexeme !~ '[''\\\\]'
),
qq AS (
    SELECT lex, cardinality(lex) AS n,
           CASE WHEN cardinality(lex) > 0
                THEN array_to_string(ARRAY(SELECT quote_literal(l) FROM unnest(lex) l), ' | ')::tsquery
           END AS q
    FROM lx
)
"""

_COVERAGE = """
CASE WHEN qq.n = 0 THEN 0
     ELSE (SELECT count(*) FROM unnest(qq.lex) l WHERE {tsv} @@ quote_literal(l)::tsquery)::float / qq.n END
"""
_RANK = "CASE WHEN qq.n = 0 THEN 0 ELSE ts_rank_cd('{{0.1, 0.2, 0.4, 1.0}}', {tsv}, qq.q, 32) END"
_FRESH = (
    "CASE WHEN {col} IS NULL THEN 0"
    " ELSE exp(-greatest(extract(epoch FROM now() - {col}) / 86400, 0) / {days}) END"
)
# у длинного фрагмента — дословное окно вокруг найденных слов; без запроса — начало (обрежет AlfaFragment)
_WINDOW = f"""
CASE WHEN length(f.fragment) <= {PUBLIC_FRAGMENT_CHARS} OR qq.q IS NULL THEN f.fragment
     ELSE ts_headline('{TS_CONFIG}', f.fragment, qq.q,
                      'MaxWords=70, MinWords=35, MaxFragments=1, StartSel="", StopSel=""') END
"""

_NEWS_COLUMNS = (
    "n.id, n.title, n.publisher, n.url, n.published_at, n.fragment, n.tags, n.expectations,"
    " n.also_reported_by"
)


class UnknownFilter(ValueError):
    """Фильтр не из каталога: агент должен узнать об ошибке, а не получить пустую выдачу."""


def _factor_codes(values: Sequence[str] | None) -> list[str]:
    if not values:
        return []
    dicts = load_dictionaries()
    by_name = {e.name.casefold(): e.code for e in dicts.factors}
    by_name[REGION_FACTOR[1]] = REGION_FACTOR[0]
    codes = {e.code for e in dicts.factors} | {REGION_FACTOR[0]}
    out = []
    for v in values:
        key = v.strip()
        code = key if key in codes else by_name.get(key.casefold())
        if code is None:
            raise UnknownFilter(f"неизвестный фактор «{v}»; коды: {', '.join(sorted(codes))}")
        out.append(code)
    return sorted(set(out))


def _sector_names() -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for e in load_dictionaries().sectors:
        names.setdefault(e.name.casefold(), set()).update(e.okved)
    for n in range(1, 100):  # названия отраслей профиля компании (api.okved)
        code = f"{n:02d}"
        if sector := sector_for(code):
            names.setdefault(sector.casefold(), set()).add(code)
    return names


def _okved_codes(values: Sequence[str] | None) -> list[str]:
    """Двузначные коды ОКВЭД из кодов (`45`, `45.31.1`) или названий отраслей разметки и профиля."""
    if not values:
        return []
    names = _sector_names()
    out: set[str] = set()
    for v in values:
        prefix = okved_prefix(v.strip())
        if prefix:
            out.add(prefix)
        elif v.strip().casefold() in names:
            out |= names[v.strip().casefold()]
        else:
            raise UnknownFilter(
                f"неизвестная отрасль «{v}»: нужен код ОКВЭД (45 или 45.31.1) или название отрасли"
            )
    return sorted(out)


def _since(value: dt.datetime | dt.date | str | None) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone(dt.timedelta(hours=3)))
    return dt.datetime.combine(value, dt.time(), tzinfo=dt.timezone(dt.timedelta(hours=3)))


def _text(value: str | None) -> str:
    """Нулевой байт PostgreSQL в тексте не принимает — запрос с ним был бы ошибкой 500."""
    return (value or "").replace("\x00", "")


def _limit(value: int) -> int:
    return max(1, min(int(value), MAX_LIMIT))


def _msk(value: dt.datetime | None) -> dt.datetime | None:
    return value.astimezone(MSK) if value is not None else None


def news_from_row(row: dict[str, Any], score: float | None = None) -> NewsItem:
    tags = row["tags"] or {}
    return NewsItem(
        id=row["id"],
        title=row["title"],
        publisher=row["publisher"],
        url=row["url"],
        published_at=_msk(row["published_at"]),
        fragment=row["fragment"],
        tags=SourceTags(
            topics=tags.get("topics", []),
            sectors=tags.get("sectors", []),
            okved=tags.get("okved", []),
            event_type=tags.get("event_type"),
            regions=tags.get("regions", []),
        ),
        factors=tags.get("factors", []),
        sector_links=tags.get("sector_links", []),
        countries=tags.get("countries", []),
        expectations=row["expectations"] or [],
        also_reported_by=row["also_reported_by"] or [],
        score=None if score is None else round(score, 4),
    )


def _alfa_from_row(row: dict[str, Any], score: float | None = None) -> AlfaFragment:
    tags = row.get("tags") or {}
    return AlfaFragment(
        id=row["id"],
        title=row["title"],
        publisher=row["publisher"],
        published_at=_msk(row["published_at"]),
        page=row.get("page"),
        fragment=row.get("window") or row.get("fragment"),
        text=row.get("fragment"),
        tags=SourceTags(topics=tags.get("topics", []), event_type=tags.get("event_type")),
        material=row["material"],
        file=row["file"],
        page_ref=row.get("page_id"),
        ocr_engine=row.get("ocr_engine"),
        stale=row["stale"],
        factors=tags.get("factors", []),
        score=None if score is None else round(score, 4),
    )


class SearchRepo:
    """Поиск и чтение материалов. `search_news`, `search_alfa_analytics`, `get_event_sources` — инструменты
    агента: возвращают `Source` по контракту (с фрагментом, у аналитики — со страницей и файлом)."""

    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    # --- инструменты агента -----------------------------------------------------------------------

    def search_news(
        self,
        query: str = "",
        factors: Sequence[str] | None = None,
        sectors: Sequence[str] | None = None,
        since: dt.datetime | dt.date | str | None = None,
        limit: int = 10,
        *,
        until: dt.datetime | dt.date | str | None = None,
        min_strength: float = 0.0,
        include_user: bool = False,
    ) -> list[NewsItem]:
        """Новости по запросу и фильтрам, лучшие первыми.

        query — слова в любой форме («ключевую ставку», «ставки ЦБ»); пустой — только фильтры, свежие первыми.
        factors — коды или названия факторов (rate, fx, «курс валют»): новость задевает хотя бы один, с силой
        ≥ min_strength. sectors — двузначные ОКВЭД, код компании или название отрасли: хотя бы одна совпадает.
        since, until — не раньше и строго раньше этой даты (until: «что ждал рынок до события»). Прислано
        пользователем на разбор — только с include_user.
        """
        items, _ = self._news(
            query, factors, sectors, since, _limit(limit), 0, min_strength, include_user, until=until
        )
        return items

    def search_alfa_analytics(
        self,
        query: str,
        topic: str | None = None,
        limit: int = 5,
        *,
        factors: Sequence[str] | None = None,
        include_stale: bool = False,
    ) -> list[AlfaFragment]:
        """Фрагменты аналитики Альфа-Банка по запросу, лучшие первыми; у каждого — материал, файл, страница,
        дата.

        topic — фактор (rate, inflation, «курс валют») или материал (keyrate-2026-09,
        src:alfa:keyrate-2026-09); другое значение добавляется к запросу словами. Устаревшие материалы
        (сталь 2021) — только с include_stale. factors — фрагмент задевает хотя бы один из факторов.
        """
        query, topic = _text(query), _text(topic) or None
        factor_codes: list[str] = _factor_codes(factors)
        material: str | None = None
        if topic:
            try:
                factor_codes = sorted(set(factor_codes) | set(_factor_codes([topic])))
            except UnknownFilter:
                mid = topic if topic.startswith("src:alfa:") else f"src:alfa:{topic}"
                if self._material_exists(mid.split("#", 1)[0]):
                    material = mid.split("#", 1)[0]
                else:
                    query = f"{query} {topic}"
        sql = f"""
            WITH {_QUERY_CTE}
            SELECT f.id, f.material, f.page_id, f.page, f.fragment, {_WINDOW} AS window, f.ocr_engine, f.tags,
                   m.title, m.publisher, m.file, m.published_at, m.stale,
                   0.6 * ({_COVERAGE.format(tsv="f.tsv")}) + 0.3 * ({_RANK.format(tsv="f.tsv")})
                   + 0.1 * {_FRESH.format(col="m.published_at", days=120)} AS score
            FROM alfa_fragments f JOIN alfa_materials m ON m.id = f.material, qq
            WHERE (qq.n = 0 OR f.tsv @@ qq.q) AND NOT (%(has_query)s AND qq.n = 0)
              AND (cardinality(%(factors)s::text[]) = 0 OR f.factors && %(factors)s::text[])
              AND (%(material)s::text IS NULL OR f.material = %(material)s)
              AND (%(stale)s OR NOT m.stale)
            ORDER BY score DESC, m.published_at DESC NULLS LAST, f.id
            LIMIT %(limit)s
        """
        params = {
            "q": query,
            "has_query": bool(query.strip()),
            "factors": factor_codes,
            "material": material,
            "stale": include_stale,
            "limit": _limit(limit),
        }
        if not (query or "").strip() and not factor_codes and material is None:
            return []  # без запроса и темы выдача была бы случайной
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            return [_alfa_from_row(r, r["score"]) for r in cur.execute(sql, params)]

    def get_event_sources(self, event_id: str) -> list[NewsItem]:
        """Все источники события: главная новость и тот же сюжет у других издателей. Нет события — пусто."""
        main = self._news_row(_text(event_id))
        if main is None:
            return []
        out = [news_from_row(main)]
        mention_ids = {news_id(m["url"]): m for m in main["also_reported_by"] or []}
        # своя строка упоминания — только из лент: присланное пользователем не становится источником события
        stored = self._news_rows(list(mention_ids), feed_only=True)
        for mid, m in mention_ids.items():
            if mid in stored:
                out.append(news_from_row(stored[mid]))
            else:
                # упоминание без своей записи: лида нет, фрагмент — заголовок
                out.append(
                    NewsItem(
                        id=mid,
                        title=m["title"],
                        publisher=m["publisher"],
                        url=m["url"],
                        published_at=m.get("published_at"),
                        fragment=m["title"],
                    )
                )
        return out

    def alfa_page_text(self, ref: str) -> str | None:
        """Распознанный текст страницы — только для самопроверки внутри сервиса, наружу не отдаётся.

        ref — фрагмент (`…#p2-3`): текст того движка, которым он распознан (tesseract — OCR, qwen3-vl — VLM);
        страница (`…#p2`): текст Tesseract, если он пуст — Qwen3-VL. Нет страницы — None.
        """
        ref = _text(ref)
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            frag = cur.execute(
                "SELECT page_id, ocr_engine FROM alfa_fragments WHERE id = %s", (ref,)
            ).fetchone()
            page = cur.execute(
                "SELECT ocr_text, vlm_text FROM alfa_pages WHERE id = %s", (frag["page_id"] if frag else ref,)
            ).fetchone()
        if page is None:
            return None
        if frag is not None and frag["ocr_engine"] == "qwen3-vl":
            return page["vlm_text"]
        return page["ocr_text"] or page["vlm_text"]

    def verify_bank_quote(self, quote: str, source_id: str) -> bool:
        """Есть ли цитата дословно (с точностью до пробелов) на странице материала банка — для самопроверки.

        source_id — фрагмент (`…#p2-3`) или страница (`…#p2`). Сверяем с текстом того движка, которым
        распознан фрагмент; у страницы — с любым из двух. Цитата короче 20 знаков или 3 слов — не проверка,
        False.
        """
        normalized = " ".join(_text(quote).split())
        if len(normalized) < MIN_QUOTE_CHARS or len(normalized.split()) < MIN_QUOTE_WORDS:
            return False
        source_id = _text(source_id)
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            frag = cur.execute(
                "SELECT page_id, ocr_engine FROM alfa_fragments WHERE id = %s", (source_id,)
            ).fetchone()
            page_id = frag["page_id"] if frag else source_id
            page = cur.execute(
                "SELECT ocr_text, vlm_text FROM alfa_pages WHERE id = %s", (page_id,)
            ).fetchone()
        if page is None:
            return False
        if frag is not None:
            text = page["vlm_text"] if frag["ocr_engine"] == "qwen3-vl" else page["ocr_text"]
            return quote_in_page(quote, text or "")
        return quote_in_page(quote, page["ocr_text"] or "") or quote_in_page(quote, page["vlm_text"] or "")

    # --- своя новость (POST /api/analyze) ---------------------------------------------------------------

    def find_news(self, source_id: str) -> NewsItem | None:
        """Новость по id — из лент или присланная на разбор (по её точному id)."""
        row = self._news_row(_text(source_id))
        return news_from_row(row) if row else None

    def save_user_news(self, item: IngestSource, body: str | None) -> bool:
        with self.pool.connection() as conn:
            return save_user_news(conn, item, body)

    # --- лента и первоисточник ----------------------------------------------------------------------

    def list_news(
        self,
        query: str = "",
        factors: Sequence[str] | None = None,
        sectors: Sequence[str] | None = None,
        since: dt.datetime | dt.date | str | None = None,
        limit: int = 20,
        offset: int = 0,
        min_strength: float = 0.0,
    ) -> NewsPage:
        items, total = self._news(query, factors, sectors, since, _limit(limit), offset, min_strength, False)
        return NewsPage(items=items, total=total, limit=_limit(limit), offset=offset)

    def get_source(self, source_id: str) -> Source | None:
        """Материал по id: новость, фрагмент аналитики (`…#p2-3`), страница (`…#p2`) или материал целиком."""
        if "\x00" in source_id:
            return None
        if source_id.startswith("src:news:"):
            row = self._news_row(source_id)
            return news_from_row(row) if row else None
        if not source_id.startswith("src:alfa:"):
            return None
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                """
                SELECT f.id, f.material, f.page_id, f.page, f.fragment, f.ocr_engine, f.tags, m.title,
                       m.publisher, m.file, m.published_at, m.stale
                FROM alfa_fragments f JOIN alfa_materials m ON m.id = f.material WHERE f.id = %s
                """,
                (source_id,),
            ).fetchone()
            if row:
                return _alfa_from_row(row)
            # страница или материал: текст страницы наружу не отдаём, только где он лежит
            row = cur.execute(
                """
                SELECT p.id, p.material, p.id AS page_id, p.page, m.title, m.publisher, m.file,
                       m.published_at, m.stale
                FROM alfa_pages p JOIN alfa_materials m ON m.id = p.material WHERE p.id = %s
                """,
                (source_id,),
            ).fetchone()
            if row:
                return _alfa_from_row(row)
            row = cur.execute(
                """
                SELECT id, id AS material, title, publisher, file, published_at, stale FROM alfa_materials
                WHERE id = %s
                """,
                (source_id,),
            ).fetchone()
        return _alfa_from_row(row) if row else None

    # --- внутреннее -------------------------------------------------------------------------------

    def _news(
        self,
        query: str,
        factors: Sequence[str] | None,
        sectors: Sequence[str] | None,
        since: dt.datetime | dt.date | str | None,
        limit: int,
        offset: int,
        min_strength: float,
        include_user: bool,
        until: dt.datetime | dt.date | str | None = None,
    ) -> tuple[list[NewsItem], int]:
        factor_codes, okved = _factor_codes(factors), _okved_codes(sectors)
        query = _text(query)
        has_query = bool(query.strip())
        order = (
            "score DESC, n.published_at DESC NULLS LAST, n.id"
            if has_query
            else "n.published_at DESC NULLS LAST, n.id"
        )
        sql = f"""
            WITH {_QUERY_CTE}
            SELECT {_NEWS_COLUMNS},
                   0.55 * ({_COVERAGE.format(tsv="n.tsv")}) + 0.25 * ({_RANK.format(tsv="n.tsv")})
                   + 0.1 * {_FRESH.format(col="n.published_at", days=7)}
                   + 0.1 * coalesce((
                       SELECT max((f->>'strength')::float) FROM jsonb_array_elements(n.tags->'factors') f
                       WHERE f->>'code' = ANY(%(factors)s::text[])), 0) AS score,
                   count(*) OVER () AS total
            FROM news n, qq
            WHERE (qq.n = 0 OR n.tsv @@ qq.q) AND NOT (%(has_query)s AND qq.n = 0)
              -- min_strength без фильтра факторов — сила связи хотя бы с одним фактором
              AND ((cardinality(%(factors)s::text[]) = 0 AND %(min_strength)s = 0) OR EXISTS (
                    SELECT 1 FROM jsonb_array_elements(n.tags->'factors') f
                    WHERE (cardinality(%(factors)s::text[]) = 0 OR f->>'code' = ANY(%(factors)s::text[]))
                      AND (f->>'strength')::float >= %(min_strength)s))
              AND (cardinality(%(okved)s::text[]) = 0 OR n.okved && %(okved)s::text[])
              AND (%(since)s::timestamptz IS NULL OR n.published_at >= %(since)s::timestamptz)
              AND (%(until)s::timestamptz IS NULL OR n.published_at < %(until)s::timestamptz)
              AND (n.origin = 'feed' OR %(include_user)s)
            ORDER BY {order}
            LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {
            "q": query,
            "has_query": has_query,
            "factors": factor_codes,
            "okved": okved,
            "since": _since(since),
            "until": _since(until),
            "min_strength": float(min_strength),
            "include_user": include_user,
            "limit": limit,
            "offset": max(0, int(offset)),
        }
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(sql, params).fetchall()
            if not rows and params["offset"] > 0:
                # за последней страницей строк нет, а значит нет и count(*) OVER () — считаем отдельно
                first = cur.execute(sql, {**params, "limit": 1, "offset": 0}).fetchone()
                return [], first["total"] if first else 0
        total = rows[0]["total"] if rows else 0
        return [news_from_row(r, r["score"] if has_query else None) for r in rows], total

    def _news_row(self, source_id: str) -> dict[str, Any] | None:
        return self._news_rows([source_id]).get(source_id)

    def _news_rows(self, ids: list[str], feed_only: bool = False) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        where = "n.id = ANY(%s)" + (" AND n.origin = 'feed'" if feed_only else "")
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(f"SELECT {_NEWS_COLUMNS} FROM news n WHERE {where}", (ids,)).fetchall()
        return {r["id"]: r for r in rows}

    def _material_exists(self, material_id: str) -> bool:
        with self.pool.connection() as conn:
            return (
                conn.execute("SELECT 1 FROM alfa_materials WHERE id = %s", (material_id,)).fetchone()
                is not None
            )
