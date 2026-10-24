from api.importer import COMPANIES_FILE, FileStats, find_file, link_rows, load_companies


def test_find_file_in_companies_subdir(data_dir, tmp_path):
    assert find_file(data_dir, COMPANIES_FILE) == data_dir / "companies" / COMPANIES_FILE
    assert find_file(tmp_path, COMPANIES_FILE) is None


def test_load_companies_tolerates_garbage_and_duplicates(data_dir):
    companies, stats = load_companies(data_dir / "companies" / COMPANIES_FILE)
    by_id = {c.id: c for c in companies}

    assert sorted(by_id) == ["U_1", "U_2", "U_3", "U_4"]
    assert stats.rows_read == 8
    assert stats.rows_loaded == 4
    # обе строки повторяющегося id U_5 (артефакт обезличивания), строка с другим числом колонок, строка без id
    assert stats.rows_skipped == 4
    # мусор в значениях — None, а не ошибка
    assert by_id["U_3"].rko is None
    assert by_id["U_3"].revenue is None
    assert by_id["U_2"].eco_mark is None


def test_link_rows(data_dir):
    stats = FileStats()
    rows = list(link_rows(data_dir / "companies" / "df_Fid_Uid_link_hack.csv", stats))
    assert rows == [("F_1", 'Мск "Юг"', "МОСКОВСКИЙ", "U_1"), ("F_2", "Тверь", None, "U_2")]
    assert stats.rows_skipped == 1
