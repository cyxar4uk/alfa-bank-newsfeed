"""Таблицы материалов в общей БД сервиса: новости и аналитика банка с полнотекстовым поиском.

Те же БД и подключение, что у API (`DATABASE_URL`). Таблицы компаний ведёт API, эти — парсер; версии схем у них
раздельные (`schema_meta`: `version` у API, `search_version` здесь), миграция одной не трогает таблицы другой.

Поиск — встроенный полнотекстовый PostgreSQL с русской конфигурацией (snowball): «ставки», «ставку», «ставкой»
сводятся к одной основе. Буква «ё» приводится к «е» и в тексте, и в запросе.
"""

import psycopg

# менять при любой правке таблиц: таблицы пересоздаются, загрузчик заново читает файлы
SCHEMA_VERSION = 1
META_KEY = "search_version"
TABLES = ("news", "news_image_stubs", "news_business", "alfa_fragments", "alfa_pages", "alfa_materials", "search_loads")

# конфигурация полнотекстового поиска; запросы в api.search строятся с ней же
TS_CONFIG = "russian"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS news (
    id               text PRIMARY KEY,
    title            text NOT NULL,
    publisher        text,
    url              text,
    published_at     timestamptz,
    fragment         text NOT NULL,
    -- полный текст: у присланных на разбор и у лент, чьи условия его разрешают (full_text в sources.toml)
    body             text,
    tags             jsonb NOT NULL DEFAULT '{{}}',
    factors          text[] NOT NULL DEFAULT '{{}}',
    okved            text[] NOT NULL DEFAULT '{{}}',
    expectations     jsonb NOT NULL DEFAULT '[]',
    also_reported_by jsonb NOT NULL DEFAULT '[]',
    -- feed — ленты и снимок; user — прислано на разбор, в ленту и поиск по умолчанию не попадает
    origin           text NOT NULL DEFAULT 'feed' CHECK (origin IN ('feed', 'user')),
    content_hash     text NOT NULL,
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('{TS_CONFIG}', translate(title, 'Ёё', 'Ее')), 'A')
        || setweight(to_tsvector('{TS_CONFIG}', translate(fragment, 'Ёё', 'Ее')), 'B')
    ) STORED
);
-- надёжность источника (official, agency, business_media, other) — добавлена после первой версии схемы
ALTER TABLE news ADD COLUMN IF NOT EXISTS reliability text;
-- ссылка на картинку материала (из ленты или og:image; файл не храним) и значок издания; media_checked_at — когда
-- страницу материала уже спрашивали о картинке и тексте, чтобы не запрашивать её каждый круг
ALTER TABLE news ADD COLUMN IF NOT EXISTS image_url text;
ALTER TABLE news ADD COLUMN IF NOT EXISTS source_icon_url text;
ALTER TABLE news ADD COLUMN IF NOT EXISTS media_checked_at timestamptz;
ALTER TABLE news ADD COLUMN IF NOT EXISTS media_attempts integer NOT NULL DEFAULT 0;
-- рыночные ряды (ingest.market): курсы и ключевая ставка ЦБ, нефть Brent; по дням, история — 90 дней
CREATE TABLE IF NOT EXISTS market_series (
    series      text NOT NULL,
    day         date NOT NULL,
    value       double precision NOT NULL,
    unit        text NOT NULL DEFAULT '',
    source      text NOT NULL DEFAULT '',
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series, day)
);
-- единица и источник — подпись в API; таблица могла быть создана без них
ALTER TABLE market_series ADD COLUMN IF NOT EXISTS unit text NOT NULL DEFAULT '';
ALTER TABLE market_series ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT '';
ALTER TABLE market_series ADD COLUMN IF NOT EXISTS fetched_at timestamptz NOT NULL DEFAULT now();
-- деловая ли новость — ответ модели для тех, что словари не решили (tags.business = null); он же кэш: второй раз
-- не спрашиваем. Переразметка словарями таблицу не трогает
CREATE TABLE IF NOT EXISTS news_business (
    id         text PRIMARY KEY,
    business   boolean NOT NULL,
    model      text NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT now()
);
-- картинки, которые сайт ставит ко многим материалам (логотип, «картинка для соцсетей») — не иллюстрации
CREATE TABLE IF NOT EXISTS news_image_stubs (
    publisher text NOT NULL,
    image_url text NOT NULL,
    PRIMARY KEY (publisher, image_url)
);
CREATE INDEX IF NOT EXISTS news_tsv_idx ON news USING gin (tsv);
CREATE INDEX IF NOT EXISTS news_factors_idx ON news USING gin (factors);
CREATE INDEX IF NOT EXISTS news_okved_idx ON news USING gin (okved);
CREATE INDEX IF NOT EXISTS news_published_idx ON news (published_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS alfa_materials (
    id           text PRIMARY KEY,          -- src:alfa:<материал>
    title        text NOT NULL,
    publisher    text NOT NULL,
    file         text,
    published_at timestamptz,
    pages        integer NOT NULL,
    -- устаревший материал (сталь 2021) позицией банка не считается и в поиск по умолчанию не идёт
    stale        boolean NOT NULL DEFAULT false
);

-- страницы целиком: только для сверки цитат банка внутри сервиса, наружу (в API) не отдаются
CREATE TABLE IF NOT EXISTS alfa_pages (
    id        text PRIMARY KEY,             -- src:alfa:<материал>#p<N>
    material  text NOT NULL REFERENCES alfa_materials (id) ON DELETE CASCADE,
    page      integer NOT NULL,
    ocr_text  text NOT NULL,                -- Tesseract
    vlm_text  text                          -- Qwen3-VL
);

CREATE TABLE IF NOT EXISTS alfa_fragments (
    id             text PRIMARY KEY,        -- src:alfa:<материал>#p<N>-<n>
    material       text NOT NULL REFERENCES alfa_materials (id) ON DELETE CASCADE,
    page_id        text NOT NULL,
    page           integer NOT NULL,
    fragment       text NOT NULL,
    ocr_engine     text,
    ocr_confidence double precision,
    tags           jsonb NOT NULL DEFAULT '{{}}',
    factors        text[] NOT NULL DEFAULT '{{}}',
    -- название материала идёт в поиск с меньшим весом: «Ключевая ставка ЦБ РФ…» помогает найти все его страницы
    title          text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('{TS_CONFIG}', translate(fragment, 'Ёё', 'Ее')), 'A')
        || setweight(to_tsvector('{TS_CONFIG}', translate(title, 'Ёё', 'Ее')), 'C')
    ) STORED
);
CREATE INDEX IF NOT EXISTS alfa_fragments_tsv_idx ON alfa_fragments USING gin (tsv);
CREATE INDEX IF NOT EXISTS alfa_fragments_factors_idx ON alfa_fragments USING gin (factors);
CREATE INDEX IF NOT EXISTS alfa_fragments_page_idx ON alfa_fragments (page_id);

-- что и когда загружено: неизменившийся файл аналитики второй раз не перечитывается
CREATE TABLE IF NOT EXISTS search_loads (
    name       text PRIMARY KEY,
    signature  text NOT NULL,
    rows       integer NOT NULL,
    loaded_at  timestamptz NOT NULL DEFAULT now()
);
"""


def ensure_schema(conn: psycopg.Connection, migrate: bool = False) -> bool:
    """Создать недостающие таблицы. migrate=True (загрузчик): при другой версии схемы — пересоздать их.
    Возвращает True, если таблицы пересозданы.

    API при старте вызывает без migrate: историю новостей стирает только загрузчик, который тут же загружает снимок
    заново. `schema_meta` создаёт и API (`api.db.ensure_schema`) — поэтому сначала берём его блокировку
    `newsfeed_schema`, потом свою: иначе одновременный старт на пустой БД падает на создании таблицы.
    """
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_schema'))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_search_schema'))")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key text PRIMARY KEY, value text NOT NULL)")
        row = conn.execute("SELECT value FROM schema_meta WHERE key = %s", (META_KEY,)).fetchone()
        migrated = migrate and row is not None and row[0] != str(SCHEMA_VERSION)
        if migrated:
            conn.execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        if row is None or migrated:
            conn.execute(
                """
                INSERT INTO schema_meta (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (META_KEY, str(SCHEMA_VERSION)),
            )
        conn.execute(SCHEMA)
    return migrated
