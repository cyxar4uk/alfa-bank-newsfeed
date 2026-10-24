"""Импорт CSV кейса в PostgreSQL: `python -m api.importer`.

Файлы ищутся в `DATA_DIR/companies/` и в `DATA_DIR/`. Импорт терпим к данным: строки с битым числом колонок
и без id пропускаются, пустые и мусорные значения становятся NULL, дубли id не роняют загрузку (берётся первая
запись, число повторов сохраняется). Файл без нужных колонок в заголовке пропускается целиком — уже
загруженные данные остаются. Уже загруженный файл с той же подписью (версия правил импорта, размер и время
изменения) повторно не грузится.
"""

import codecs
import csv
import logging
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import astuple, dataclass
from pathlib import Path

import psycopg

from api.config import get_settings
from api.db import GROUPS_FILL, PAYMENT_INDEXES, SCHEMA_VERSION, connect, ensure_schema
from api.okved import okved_prefix
from api.records import COMPANY_FIELDS, CompanyRecord, clean_id, clean_text, company_from_row

log = logging.getLogger("api.importer")

COMPANIES_FILE = "df_Uid_data_hack.csv"
PAYMENTS_FILE = "df_Uid_payment_hack.csv"
LINKS_FILE = "df_Fid_Uid_link_hack.csv"
DATA_FILES = [COMPANIES_FILE, PAYMENTS_FILE, LINKS_FILE]

# колонки, без которых файл не грузится
REQUIRED_COLUMNS = {
    COMPANIES_FILE: {"SYNTHETIC_U"},
    PAYMENTS_FILE: {"BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"},
    LINKS_FILE: {"SYNTHETIC_F", "SYNTHETIC_U"},
}


@dataclass
class FileStats:
    rows_read: int = 0
    rows_loaded: int = 0
    rows_skipped: int = 0


def find_file(data_dir: Path, name: str) -> Path | None:
    for candidate in (data_dir / "companies" / name, data_dir / name):
        if candidate.is_file():
            return candidate
    return None


def signature(path: Path) -> str:
    stat = path.stat()
    # версия правил в подписи: поменялись схема или очистка — файл перечитается
    return f"v{SCHEMA_VERSION}:{stat.st_size}:{stat.st_mtime_ns}"


def read_header(path: Path) -> list[str]:
    with path.open("rb") as f:
        line = f.readline().decode("utf-8-sig", errors="replace")
    return [h.strip().strip('"').upper() for h in line.split(";")]


def read_rows(path: Path, stats: FileStats) -> Iterator[dict[str, str]]:
    """Строки CSV (UTF-8, `;`) как словари по заголовку; строки с другим числом колонок пропускаются."""
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        header = [h.strip().upper() for h in next(reader, [])]
        for row in reader:
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            stats.rows_read += 1
            if len(row) != len(header):
                stats.rows_skipped += 1
                continue
            yield dict(zip(header, row, strict=True))


def load_companies(path: Path) -> tuple[list[CompanyRecord], FileStats]:
    stats = FileStats()
    companies: dict[str, CompanyRecord] = {}
    rows: Counter[str] = Counter()
    for row in read_rows(path, stats):
        record = company_from_row(row)
        if record is None:
            stats.rows_skipped += 1
            continue
        rows[record.id] += 1
        companies.setdefault(record.id, record)
    # id в нескольких строках — артефакт обезличивания (ответ организаторов): почти пустые строки разных
    # компаний под одним id; ни одна из них не настоящая — убираем все
    repeated = {company_id for company_id, n in rows.items() if n > 1}
    for company_id in repeated:
        companies.pop(company_id)
        stats.rows_skipped += rows[company_id]
    if repeated:
        log.info("%s: убраны id в нескольких строках: %s", path.name, ", ".join(sorted(repeated)))
    stats.rows_loaded = len(companies)
    return list(companies.values()), stats


def link_rows(path: Path, stats: FileStats) -> Iterator[tuple[str, str | None, str | None, str]]:
    for row in read_rows(path, stats):
        person = clean_id(row.get("SYNTHETIC_F"))
        company = clean_id(row.get("SYNTHETIC_U"))
        if not person or not company:
            stats.rows_skipped += 1
            continue
        stats.rows_loaded += 1
        yield person, clean_text(row.get("CITY_NAME")), clean_text(row.get("RC_NAME")), company


def _already_loaded(conn: psycopg.Connection, name: str, sig: str) -> bool:
    row = conn.execute("SELECT signature FROM imported_files WHERE file = %s", (name,)).fetchone()
    return row is not None and row[0] == sig


def _record(conn: psycopg.Connection, name: str, sig: str, stats: FileStats) -> None:
    conn.execute(
        """
        INSERT INTO imported_files (file, signature, rows_read, rows_loaded, rows_skipped, loaded_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (file) DO UPDATE SET signature = EXCLUDED.signature, rows_read = EXCLUDED.rows_read,
            rows_loaded = EXCLUDED.rows_loaded, rows_skipped = EXCLUDED.rows_skipped, loaded_at = now()
        """,
        (name, sig, stats.rows_read, stats.rows_loaded, stats.rows_skipped),
    )


def import_companies(conn: psycopg.Connection, path: Path) -> FileStats:
    companies, stats = load_companies(path)
    columns = ", ".join([*COMPANY_FIELDS, "okved_class"])
    with conn.transaction():
        conn.execute("TRUNCATE companies")
        with conn.cursor().copy(f"COPY companies ({columns}) FROM STDIN") as copy:
            for record in companies:
                copy.write_row((*astuple(record), okved_prefix(record.okved_code)))
        conn.execute("TRUNCATE company_groups")
        conn.execute(GROUPS_FILL)
        _record(conn, COMPANIES_FILE, signature(path), stats)
    return stats


# Платежи грузятся одним COPY прямо в таблицу: разбор в PostgreSQL, 1,4 млн строк — секунды.
# Если в файле мусор (битое число, лишняя колонка, пустое поле) или COPY загрузил не все строки, откатываемся
# к точке сохранения и грузим терпимо: строки как есть во временную таблицу, чистка одним INSERT ... SELECT.
# Оба пути одинаково обрезают пробелы и кавычки вокруг полей; `;` внутри кавычек не поддерживается
# (в платежах его нет — только id и числа).
_ID_PATTERN = r"^[A-Za-z]+_[0-9]+$"
_PAYMENT_COLUMNS = {
    "BENEFICIARY": "beneficiary",
    "PAYER": "payer",
    "PAY_AMT": "amount",
    "PAY_CNT": "payments",
}

_RAW_COPY = r"COPY payments_raw (line) FROM STDIN WITH (FORMAT csv, DELIMITER E'\x01', QUOTE E'\x02')"
# символы, которые ломают COPY: NUL и наши служебные разделитель и кавычка
_UNSAFE = {0: None, 1: None, 2: None}
# строка «\.» — конец данных для COPY; в терпимом пути её просто выбрасываем
_END_OF_DATA = re.compile(r"^\\\.\r?$")

# после быстрого COPY: обрезать пробелы у id, убрать строки с мусорными id и суммами
_PAYMENTS_TRIM = r"""
UPDATE payments SET beneficiary = btrim(beneficiary, E' \t\r'), payer = btrim(payer, E' \t\r')
WHERE beneficiary <> btrim(beneficiary, E' \t\r') OR payer <> btrim(payer, E' \t\r')
"""
_PAYMENTS_CLEANUP = r"""
DELETE FROM payments
WHERE beneficiary !~ %(id)s OR payer !~ %(id)s OR NOT (amount > 0 AND amount < 'Infinity')
"""

# терпимый путь: поле — split_part по номеру колонки из заголовка, число колонок — по числу разделителей,
# числа — через pg_input_is_valid, чтобы мусор отсеивался без ошибки приведения
_PAYMENTS_INSERT = r"""
INSERT INTO payments (beneficiary, payer, amount, payments)
SELECT beneficiary, payer, amount::double precision,
       CASE WHEN pg_input_is_valid(cnt, 'double precision')
                 AND cnt::double precision BETWEEN 1 AND 2147483647
            THEN round(cnt::double precision)::integer ELSE 1 END
FROM (
    SELECT btrim(split_part(line, ';', %(b)s), E' \t\r"') AS beneficiary,
           btrim(split_part(line, ';', %(p)s), E' \t\r"') AS payer,
           replace(btrim(split_part(line, ';', %(a)s), E' \t\r"'), ',', '.') AS amount,
           replace(btrim(split_part(line, ';', %(c)s), E' \t\r"'), ',', '.') AS cnt
    FROM payments_raw
    WHERE length(line) - length(replace(line, ';', '')) = %(n)s - 1
) t
WHERE beneficiary ~ %(id)s AND payer ~ %(id)s
  AND CASE WHEN pg_input_is_valid(amount, 'double precision')
           THEN amount::double precision > 0 AND amount::double precision < 'Infinity' ELSE false END
"""


class _Incomplete(Exception):
    """Быстрый COPY загрузил не все строки файла."""


def _copy_payments_fast(conn: psycopg.Connection, path: Path, header: list[str]) -> int:
    """COPY файла прямо в payments; мусор — psycopg.Error, потеря строк — _Incomplete."""
    columns = ", ".join(_PAYMENT_COLUMNS[name] for name in header)
    query = f"COPY payments ({columns}) FROM STDIN WITH (FORMAT csv, DELIMITER ';', HEADER true)"
    lines = 0
    last = b"\n"
    with path.open("rb") as f, conn.cursor() as cur:
        with cur.copy(query) as copy:
            while chunk := f.read(1 << 20):
                lines += chunk.count(b"\n")
                last = chunk[-1:]
                copy.write(chunk)
        rows = cur.rowcount
    # строк данных = переводов строки минус заголовок (+1, если файл не кончается переводом строки)
    expected = lines - 1 + (last != b"\n")
    if rows != expected:
        raise _Incomplete(f"загружено {rows} строк из {expected}")
    return rows


def _copy_payments_tolerant(
    conn: psycopg.Connection, path: Path, header: list[str], stats: FileStats
) -> None:
    conn.execute("CREATE TEMP TABLE payments_raw (line text) ON COMMIT DROP")
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def lines(text: str) -> bytes:
        # пустые строки, маркер конца данных «\.» и возвраты каретки (CRLF, смешанные концы, \r в поле)
        # COPY не принимает: строки без них выбрасываем, \r в конце снимаем, внутри — заменяем пробелом
        kept = [
            line.rstrip("\r").replace("\r", " ")
            for line in text.split("\n")
            if line.strip() and not _END_OF_DATA.match(line)
        ]
        return ("\n".join(kept) + "\n").encode() if kept else b""

    with path.open("rb") as f, conn.cursor().copy(_RAW_COPY) as copy:
        f.readline()  # заголовок
        tail = ""  # незаконченная строка с конца прошлого куска
        while chunk := f.read(1 << 20):
            complete, _, tail = (tail + decoder.decode(chunk).translate(_UNSAFE)).rpartition("\n")
            copy.write(lines(complete))
        copy.write(lines(tail + decoder.decode(b"", final=True).translate(_UNSAFE)))
    count = conn.execute("SELECT count(*) FROM payments_raw WHERE btrim(line, E' \t\r') <> ''")
    stats.rows_read = count.fetchone()[0]
    # номера колонок для split_part — с единицы
    b, p, a, c = (header.index(name) + 1 for name in _PAYMENT_COLUMNS)
    params = {"b": b, "p": p, "a": a, "c": c, "n": len(header), "id": _ID_PATTERN}
    stats.rows_loaded = conn.execute(_PAYMENTS_INSERT, params).rowcount
    stats.rows_skipped = stats.rows_read - stats.rows_loaded


def import_payments(conn: psycopg.Connection, path: Path) -> FileStats:
    stats = FileStats()
    header = read_header(path)
    with conn.transaction():
        conn.execute("DROP INDEX IF EXISTS payments_payer_idx")
        conn.execute("DROP INDEX IF EXISTS payments_beneficiary_idx")
        # TRUNCATE и COPY в одной транзакции: при wal_level=minimal журнал не пишется
        conn.execute("TRUNCATE payments")
        fast = sorted(header) == sorted(_PAYMENT_COLUMNS)
        if fast:
            try:
                with conn.transaction():
                    stats.rows_read = _copy_payments_fast(conn, path, header)
                    conn.execute(_PAYMENTS_TRIM)
                    deleted = conn.execute(_PAYMENTS_CLEANUP, {"id": _ID_PATTERN}).rowcount
                    conn.execute("UPDATE payments SET payments = 1 WHERE payments < 1")
                stats.rows_loaded = stats.rows_read - deleted
                stats.rows_skipped = deleted
            except (psycopg.Error, _Incomplete) as error:
                reason = error.diag.message_primary if isinstance(error, psycopg.Error) else str(error)
                log.info("%s: в файле есть мусор (%s) — разбираю построчно", path.name, reason)
                fast = False
        if not fast:
            _copy_payments_tolerant(conn, path, header, stats)
        conn.execute(PAYMENT_INDEXES)
        _record(conn, PAYMENTS_FILE, signature(path), stats)
    conn.execute("ANALYZE payments")
    return stats


def import_links(conn: psycopg.Connection, path: Path) -> FileStats:
    stats = FileStats()
    with conn.transaction():
        conn.execute("TRUNCATE person_links")
        with conn.cursor().copy(
            "COPY person_links (person_id, city_name, rc_name, company_id) FROM STDIN"
        ) as copy:
            for row in link_rows(path, stats):
                copy.write_row(row)
        _record(conn, LINKS_FILE, signature(path), stats)
    return stats


IMPORTERS = [
    (COMPANIES_FILE, import_companies),
    (PAYMENTS_FILE, import_payments),
    (LINKS_FILE, import_links),
]


def import_all(conn: psycopg.Connection, data_dir: Path, force: bool = False) -> dict[str, FileStats]:
    # пересоздать таблицы под новую схему можно, только когда все три файла есть и годны к загрузке:
    # иначе старые данные оставляем как есть, а не стираем без замены
    unusable = []
    for name, _ in IMPORTERS:
        path = find_file(data_dir, name)
        if path is None or REQUIRED_COLUMNS[name] - set(read_header(path)):
            unusable.append(name)
    can_reload = not unusable
    if not can_reload:
        log.warning(
            "нет годных файлов %s в %s — схему и загруженные данные не трогаю", ", ".join(unusable), data_dir
        )
    ensure_schema(conn, migrate=can_reload)
    results: dict[str, FileStats] = {}
    for name, importer in IMPORTERS:
        path = find_file(data_dir, name)
        if path is None:
            log.warning("нет файла %s в %s — пропускаю", name, data_dir)
            continue
        absent = REQUIRED_COLUMNS[name] - set(read_header(path))
        if absent:
            log.warning("%s: в заголовке нет колонок %s — файл пропущен", name, ", ".join(sorted(absent)))
            continue
        if not force and _already_loaded(conn, name, signature(path)):
            log.info("%s уже загружен", name)
            continue
        log.info("загружаю %s", path)
        stats = importer(conn, path)
        log.info(
            "%s: прочитано %d, загружено %d, пропущено %d",
            name,
            stats.rows_read,
            stats.rows_loaded,
            stats.rows_skipped,
        )
        results[name] = stats
    conn.execute("ANALYZE companies")
    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    with connect(settings.database_url, attempts=60) as conn:
        conn.autocommit = True
        import_all(conn, settings.data_dir, force=settings.import_force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
