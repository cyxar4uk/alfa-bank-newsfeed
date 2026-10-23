"""Схема БД и подключение."""

import time

import psycopg

# менять при любой правке схемы или правил очистки: импорт пересоздаст таблицы и перечитает файлы
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              text PRIMARY KEY,
    org_type        text,
    okfs_name       text,
    age_gradation   text,
    eco_mark        text,
    okved_code      text,
    okved_name      text,
    negative_mark   boolean,
    workers_fns     text,
    workers_spark   text,
    client_type     text,
    rko             boolean,
    guarantee       boolean,
    credit          boolean,
    leasing         boolean,
    deposit         boolean,
    salary_project  boolean,
    fts_flag        boolean,
    fts_countries   text,
    factoring       boolean,
    revenue         double precision,
    group_id        text,
    city            text,
    region          text,
    duplicates      integer NOT NULL DEFAULT 1,
    -- двузначный класс ОКВЭД, считается при импорте (api.okved.okved_prefix); мусорный код — NULL
    okved_class     text
);
CREATE INDEX IF NOT EXISTS companies_group_idx ON companies (group_id);
CREATE INDEX IF NOT EXISTS companies_class_idx ON companies (okved_class, revenue);
CREATE INDEX IF NOT EXISTS companies_revenue_idx ON companies (revenue DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS payments (
    beneficiary text NOT NULL,
    payer       text NOT NULL,
    amount      double precision NOT NULL,
    payments    integer NOT NULL
);

CREATE TABLE IF NOT EXISTS person_links (
    person_id   text NOT NULL,
    city_name   text,
    rc_name     text,
    company_id  text NOT NULL
);

CREATE TABLE IF NOT EXISTS imported_files (
    file        text PRIMARY KEY,
    signature   text NOT NULL,
    rows_read   integer NOT NULL,
    rows_loaded integer NOT NULL,
    rows_skipped integer NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now()
);
"""

# индексы платежей строятся после загрузки — так COPY быстрее
PAYMENT_INDEXES = """
CREATE INDEX IF NOT EXISTS payments_payer_idx ON payments (payer);
CREATE INDEX IF NOT EXISTS payments_beneficiary_idx ON payments (beneficiary);
CREATE INDEX IF NOT EXISTS person_links_company_idx ON person_links (company_id);
"""


def connect(url: str, attempts: int = 30, delay: float = 1.0) -> psycopg.Connection:
    """Подключиться, дождавшись БД (в compose она может стартовать позже)."""
    for attempt in range(1, attempts + 1):
        try:
            return psycopg.connect(url)
        except psycopg.OperationalError:
            if attempt == attempts:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")


def ensure_schema(conn: psycopg.Connection, migrate: bool = False) -> None:
    """Создать таблицы. `migrate=True` (импорт): при другой версии схемы — пересоздать их с нуля.

    Параллельные вызовы (API и импорт на свежей БД) сериализуются рекомендательной блокировкой.
    """
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('newsfeed_schema'))")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key text PRIMARY KEY, value text NOT NULL)")
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
        # нет версии — таблицы могли остаться от старой схемы; на пустой БД удалять просто нечего
        if migrate and (row is None or row[0] != str(SCHEMA_VERSION)):
            conn.execute("DROP TABLE IF EXISTS companies, payments, person_links, imported_files")
            conn.execute(
                """
                INSERT INTO schema_meta (key, value) VALUES ('version', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (str(SCHEMA_VERSION),),
            )
        conn.execute(SCHEMA)
