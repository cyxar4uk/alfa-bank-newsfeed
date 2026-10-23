from api.records import CompanyRecord


def make_company(**overrides) -> CompanyRecord:
    """Крупная оптовая компания со всеми полями; overrides — что поменять."""
    values = dict(
        id="U_1",
        org_type="КОММ_ОРГ",
        okfs_name="ЧАСТНАЯ СОБСТВЕННОСТЬ",
        age_gradation="16-25",
        eco_mark="Оптимизация",
        okved_code="46.71",
        okved_name="Торговля оптовая твердым, жидким и газообразным топливом",
        negative_mark=False,
        workers_fns="Более 251",
        workers_spark=None,
        client_type="CLIENT",
        rko=True,
        guarantee=False,
        credit=True,
        leasing=True,
        deposit=False,
        salary_project=True,
        fts_flag=True,
        fts_countries="КИТАЙ, ОАЭ, ЮЖНАЯ КОРЕЯ",
        factoring=False,
        revenue=20e9,
        group_id="group_1_sb",
        city="г. Москва",
        region="Москва",
    )
    values.update(overrides)
    return CompanyRecord(**values)
