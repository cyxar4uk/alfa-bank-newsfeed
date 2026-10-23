"""Импорт и чтение из настоящего PostgreSQL. Запускается, если задан TEST_DATABASE_URL (БД очищается)."""

import os

import pytest

from api.importer import import_all
from api.profile import build_profile

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL не задан")


@pytest.fixture
def repo(data_dir):
    import psycopg
    from psycopg_pool import ConnectionPool

    from api.repo import PgCompanyRepo

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS companies, payments, person_links, imported_files")
        stats = import_all(conn, data_dir)
        assert stats["df_Uid_data_hack.csv"].rows_loaded == 4
        payments = stats["df_Uid_payment_hack.csv"]
        # пустой плательщик, сумма-текст, отрицательная сумма, лишняя колонка — пропущены
        assert (payments.rows_read, payments.rows_loaded, payments.rows_skipped) == (10, 6, 4)
        first = conn.execute("SELECT * FROM payments WHERE payer = 'U_1' AND beneficiary = 'U_2'").fetchone()
        assert first == ("U_2", "U_1", 3e9, 120)
        # повторный запуск с теми же файлами ничего не грузит
        assert import_all(conn, data_dir) == {}
    with ConnectionPool(URL, min_size=1, max_size=2) as pool:
        yield PgCompanyRepo(pool)


def test_profile_from_db(repo):
    company = repo.get_company("U_1")
    assert company.duplicates == 2
    size, members = repo.group(company.group_id, exclude="U_1", limit=20)
    assert (size, members) == (2, ["U_2"])

    profile = build_profile(company, repo.flows("U_1"), size, members)
    assert [c.id for c in profile.counterparties] == ["U_2", "U_77", "U_4"]
    assert profile.counterparties[0].sector == "транспорт и логистика"
    assert profile.counterparties[0].role == "both"
    # строка U_1 → U_1 одна, и посчитана она один раз
    assert profile.payments.excluded_self_payments == 1


def test_industry_position(repo):
    # U_4 — единственная компания с 35.11; U_1 (46.71) — тоже одна в своём коде
    position = repo.industry(repo.get_company("U_4"))
    assert (position.rank, position.total, position.okved_class, position.class_total) == (1, 1, "35", 1)
    assert position.percentile == 0
    assert repo.industry(repo.get_company("U_3")) is None  # выручка — мусор в CSV


def test_large_and_files(repo):
    assert [c.id for c in repo.list_companies(large=True, limit=10, offset=0)] == ["U_1", "U_4"]
    assert {f.file for f in repo.imported_files()} == {
        "df_Uid_data_hack.csv",
        "df_Uid_payment_hack.csv",
        "df_Fid_Uid_link_hack.csv",
    }


def test_clean_payments_go_fast_path(tmp_path):
    import psycopg

    from api.importer import import_payments

    path = tmp_path / "df_Uid_payment_hack.csv"
    # колонки в другом порядке, мусорный id — COPY проходит, строку убирает чистка
    path.write_text(
        "PAYER;BENEFICIARY;PAY_CNT;PAY_AMT\nU_1;U_2;3;100.5\nU_2;U_1;0;7\nмусор;U_1;1;5\n", "utf-8"
    )
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS companies, payments, person_links, imported_files")
        from api.db import ensure_schema

        ensure_schema(conn)
        stats = import_payments(conn, path)
        rows = conn.execute(
            "SELECT beneficiary, payer, amount, payments FROM payments ORDER BY payer"
        ).fetchall()
    assert (stats.rows_read, stats.rows_loaded, stats.rows_skipped) == (3, 2, 1)
    assert rows == [("U_2", "U_1", 100.5, 3), ("U_1", "U_2", 7.0, 1)]


def _payments_file(tmp_path, text):
    path = tmp_path / "df_Uid_payment_hack.csv"
    path.write_text(text, "utf-8")
    return path


def _load(path):
    import psycopg

    from api.db import ensure_schema
    from api.importer import import_payments

    with psycopg.connect(URL, autocommit=True) as conn:
        ensure_schema(conn, migrate=True)
        stats = import_payments(conn, path)
        rows = conn.execute("SELECT beneficiary, payer, amount FROM payments ORDER BY amount").fetchall()
    return stats, rows


def test_fast_and_tolerant_paths_agree_on_spaces_and_quotes(tmp_path):
    clean = 'BENEFICIARY;PAYER;PAY_AMT;PAY_CNT\nU_2 ;U_1;100;1\n"U_3";"U_1";"200";"2"\n'
    fast_stats, fast_rows = _load(_payments_file(tmp_path, clean))
    # та же пара строк плюс мусор — включается терпимый путь
    tolerant_stats, tolerant_rows = _load(_payments_file(tmp_path, clean + "U_4;U_1;abc;1\n"))
    expected = [("U_2", "U_1", 100.0), ("U_3", "U_1", 200.0)]
    assert fast_rows == expected
    assert tolerant_rows == expected
    assert (fast_stats.rows_loaded, tolerant_stats.rows_loaded, tolerant_stats.rows_skipped) == (2, 2, 1)


def test_end_of_data_marker_does_not_cut_file(tmp_path):
    stats, rows = _load(
        _payments_file(tmp_path, "BENEFICIARY;PAYER;PAY_AMT;PAY_CNT\nU_2;U_1;1;1\n\\.\nU_3;U_1;2;1\n")
    )
    assert rows == [("U_2", "U_1", 1.0), ("U_3", "U_1", 2.0)]


def test_bad_header_skips_file_and_keeps_data(tmp_path, data_dir):
    import shutil

    import psycopg

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS companies, payments, person_links, imported_files, schema_meta")
        import_all(conn, data_dir)
        bad = tmp_path / "companies"
        bad.mkdir()
        (bad / "df_Uid_data_hack.csv").write_text("id,name\nU_1,x\n", "utf-8")  # не тот разделитель
        (bad / "df_Uid_payment_hack.csv").write_text("", "utf-8")  # пустой файл
        shutil.copy(data_dir / "companies" / "df_Fid_Uid_link_hack.csv", bad)
        # заголовок в нижнем регистре — тоже годится
        links = (bad / "df_Fid_Uid_link_hack.csv").read_text("utf-8").replace("SYNTHETIC_F", "synthetic_f")
        (bad / "df_Fid_Uid_link_hack.csv").write_text(links, "utf-8")
        stats = import_all(conn, tmp_path, force=True)
        assert set(stats) == {"df_Fid_Uid_link_hack.csv"}
        assert stats["df_Fid_Uid_link_hack.csv"].rows_loaded == 2
        assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 4
        assert conn.execute("SELECT count(*) FROM payments").fetchone()[0] == 6


def test_schema_version_change_recreates_tables(data_dir, monkeypatch):
    import psycopg

    from api import db, importer

    with psycopg.connect(URL, autocommit=True) as conn:
        import_all(conn, data_dir)
        conn.execute("ALTER TABLE companies DROP COLUMN region")  # схема «старой версии»
        monkeypatch.setattr(db, "SCHEMA_VERSION", 999)
        monkeypatch.setattr(importer, "SCHEMA_VERSION", 999)
        stats = import_all(conn, data_dir)  # подпись другая — файлы перечитаны без IMPORT_FORCE
        assert stats["df_Uid_data_hack.csv"].rows_loaded == 4
        region = conn.execute("SELECT region FROM companies WHERE id = 'U_1'").fetchone()[0]
        assert region == "Москва"


def test_concurrent_ensure_schema():
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    from api.db import ensure_schema

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS companies, payments, person_links, imported_files, schema_meta")

    def run(_):
        with psycopg.connect(URL) as conn:
            ensure_schema(conn)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(run, range(4)))


def test_tolerant_path_handles_carriage_returns(tmp_path):
    raw = (
        b"BENEFICIARY;PAYER;PAY_AMT;PAY_CNT\r\n"
        b"U_2;U_1;1;1\r\n"
        b"U_3;U_1;2;1\n"  # смешанные концы строк
        b"U_4;U_1;3;2\r5\r\n"  # \r внутри поля — сумма-мусор не страдает, число платежей становится 1
        b"U_5;U_1;abc;1\r\n"  # мусор — включает терпимый путь
        b"U_6;U_1;4;1"  # без перевода строки в конце
    )
    path = tmp_path / "df_Uid_payment_hack.csv"
    path.write_bytes(raw)
    stats, rows = _load(path)
    assert rows == [("U_2", "U_1", 1.0), ("U_3", "U_1", 2.0), ("U_4", "U_1", 3.0), ("U_6", "U_1", 4.0)]
    assert (stats.rows_read, stats.rows_skipped) == (5, 1)
