from api.records import clean_flag, clean_id, clean_number, clean_text, company_from_row


def test_clean_values():
    assert clean_text("  Москва ") == "Москва"
    assert clean_text("   ") is None
    assert clean_text("nan") is None
    assert clean_flag("1.0") is True
    assert clean_flag("0.0") is False
    assert clean_flag("мусор") is None
    assert clean_number("16461799989.0") == 16461799989.0
    assert clean_number("1,5") == 1.5
    assert clean_number("не число") is None
    assert clean_number("inf") is None
    assert clean_id("U_123") == "U_123"
    assert clean_id("123") is None
    assert clean_id("") is None


def test_company_from_row_tolerates_garbage():
    record = company_from_row(
        {
            "SYNTHETIC_U": "U_3",
            "MAINOKVED_CODE": " 41.20 ",
            "CL_PRODUCT_RKO_MARK": "мусор",
            "REVENUE_COMPANY": "0.0",
            "FTS_COUNTRY_NAME": "",
        }
    )
    assert record is not None
    assert record.okved_code == "41.20"
    assert record.rko is None
    assert record.revenue is None  # нулевая выручка — нет данных
    assert record.fts_countries is None
    assert record.region is None  # колонки нет вовсе


def test_company_without_id_is_skipped():
    assert company_from_row({"SYNTHETIC_U": "", "CITY": "г. Москва"}) is None
