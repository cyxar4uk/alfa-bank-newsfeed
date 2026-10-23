from api.okved import SECTOR_BY_CODE, okved_prefix, sector_for


def test_prefix_variants():
    assert okved_prefix("46.34") == "46"
    assert okved_prefix("41.2") == "41"
    assert okved_prefix("68.32.1") == "68"
    assert okved_prefix("46") == "46"
    assert okved_prefix("мусор") is None
    assert okved_prefix(None) is None


def test_sectors():
    assert sector_for("46.71") == "оптовая торговля"
    assert sector_for("45.31.1") == "автомобили"
    assert sector_for("35.11") == "энергетика"
    assert sector_for("00.00") is None


def test_every_code_in_dataset_has_sector():
    # все двузначные коды, которые встречаются в выгрузке кейса
    codes = (
        "01 02 03 06 07 08 09 10 11 13 14 15 16 17 18 20 21 22 23 24 25 26 27 28 29 30 31 32 33 35 36 37 38 "
        "41 42 43 45 46 47 49 50 52 53 55 56 58 59 60 61 62 63 64 66 68 69 70 71 72 73 74 75 77 78 79 80 81 "
        "82 85 86 87 88 90 93 94 95 96"
    ).split()
    assert [c for c in codes if c not in SECTOR_BY_CODE] == []
