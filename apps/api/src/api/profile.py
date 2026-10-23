"""Сборка профиля компании из записи выгрузки, её группы и платежей."""

from collections import defaultdict
from dataclasses import dataclass

from api.contract import (
    CompanyGroup,
    CompanyProfile,
    Counterparty,
    Feature,
    IndustryPosition,
    MissingFeature,
    PaymentSide,
    PaymentStructure,
    SectorShare,
)
from api.okved import SECTOR_BY_CODE, okved_prefix, sector_for
from api.records import CompanyRecord, Flow

LARGE_REVENUE = 15e9  # крупный бизнес по кейсу
TOP_COUNTERPARTIES = 10
GROUP_MEMBERS_SHOWN = 20
# пара с суммой больше годовой выручки компании — явный выброс (обычно внутригрупповые переводы)
OUTLIER_REVENUE_RATIO = 1.0
# платёжный оборот меньше этой доли выручки — честно предупреждаем, что контрагенты видны не все
LOW_COVERAGE = 0.1

CLIENT_TYPES = {
    "CLIENT": "действующий клиент",
    "CLOSE_CLIENT": "бывший клиент",
    "PROSPECT": "потенциальный клиент",
}

# поле записи, id признака, подпись, короткое название продукта
PRODUCTS = [
    ("rko", "CL_PRODUCT_RKO_MARK", "РКО в банке", "РКО"),
    ("credit", "CL_PRODUCT_LOA_MARK", "Кредиты в банке", "кредиты"),
    ("guarantee", "CL_PRODUCT_GAR_MARK", "Гарантии в банке", "гарантии"),
    ("leasing", "CL_PRODUCT_LEA_MARK", "Лизинг в банке", "лизинг"),
    ("deposit", "CL_PRODUCT_DEP_MARK", "Депозиты в банке", "депозиты"),
    ("salary_project", "CL_PRODUCT_ZPP_MARK", "Зарплатный проект в банке", "зарплатный проект"),
    ("factoring", "FACTORING_MARK", "Факторинг в банке", "факторинг"),
]

_ROLE_NAMES = {"supplier": "поставщик", "customer": "покупатель", "both": "поставщик и покупатель"}


def company_number(company_id: str) -> str:
    return company_id.rsplit("_", 1)[-1]


def display_name(company: CompanyRecord | None, company_id: str) -> str:
    name = f"Компания №{company_number(company_id)}"
    activity = company.okved_name if company else None
    if activity:
        name += f" · {activity[0].lower()}{activity[1:]}"
    return name


def format_rub(amount: float) -> str:
    for scale, unit in ((1e12, "трлн"), (1e9, "млрд"), (1e6, "млн"), (1e3, "тыс.")):
        if abs(amount) >= scale:
            return f"{amount / scale:.1f}".replace(".", ",") + f" {unit} ₽"
    return f"{amount:.0f} ₽"


def format_share(share: float) -> str:
    percent = share * 100
    return f"{percent:.0f} %" if percent >= 1 else f"{percent:.1f} %".replace(".", ",")


def scale_for(revenue: float) -> str:
    if revenue > LARGE_REVENUE:
        return "крупный бизнес"
    if revenue > 2e9:
        return "средний бизнес"  # нижняя граница крупного по закону — 2 млрд, по кейсу — 15 млрд
    if revenue > 120e6:
        return "малый бизнес"
    return "микробизнес"


def countries(raw: str) -> list[str]:
    result = []
    for name in raw.split(","):
        name = name.strip()
        if not name:
            continue
        # аббревиатуры (ОАЭ, США) оставляем как есть, остальное — каждое слово с заглавной буквы
        if len(name) > 3:
            name = " ".join(w.lower() if w.lower() in {"и", "о"} else w.capitalize() for w in name.split())
        result.append(name)
    return result


class _Builder:
    def __init__(self) -> None:
        self.features: list[Feature] = []
        self.missing: list[MissingFeature] = []
        self.notes: list[str] = []

    def dataset(self, column: str, label: str, value, display: str | None = None) -> None:
        feature_id = f"feat:{column}"
        if value is None:
            self.missing.append(MissingFeature(id=feature_id, label=label))
            return
        self.features.append(
            Feature(id=feature_id, label=label, value=value, display=display, source="dataset")
        )

    def derived(
        self,
        name: str,
        label: str,
        value,
        derived_from: list[str],
        display: str | None = None,
        reason: str = "не из чего вычислить",
    ) -> None:
        feature_id = f"feat:{name}"
        if value is None:
            self.missing.append(MissingFeature(id=feature_id, label=label, reason=reason))
            return
        self.features.append(
            Feature(
                id=feature_id,
                label=label,
                value=value,
                display=display,
                source="derived",
                derived_from=derived_from,
            )
        )


@dataclass
class _Pair:
    out_amount: float = 0.0
    in_amount: float = 0.0
    payments: int = 0
    counterparty: CompanyRecord | None = None


def build_profile(
    company: CompanyRecord,
    flows: list[Flow],
    group_size: int = 1,
    group_members: list[str] | None = None,
    industry: IndustryPosition | None = None,
) -> CompanyProfile:
    b = _Builder()

    # деятельность и отрасль
    activity = None
    if company.okved_code:
        activity = f"{company.okved_code} {company.okved_name}" if company.okved_name else company.okved_code
    b.dataset("MAINOKVED_CODE", "Основная деятельность", activity)
    b.derived("sector", "Отрасль", sector_for(company.okved_code), ["feat:MAINOKVED_CODE"])
    _industry(industry, b)

    # масштаб
    revenue = company.revenue
    b.dataset("REVENUE_COMPANY", "Выручка", revenue, display=format_rub(revenue) if revenue else None)
    b.derived(
        "scale",
        "Масштаб",
        scale_for(revenue) if revenue else None,
        ["feat:REVENUE_COMPANY"],
        reason="нет выручки",
    )
    b.dataset("AMOUNT_WORKERS_FNS_GRADATION", "Сотрудники по данным ФНС", company.workers_fns)
    b.dataset("AMOUNT_WORKERS_SPARK_GRADATION", "Сотрудники по данным СПАРК", company.workers_spark)
    b.dataset("COMPANY_AGE_YEARS_GRADATION", "Возраст компании, лет", company.age_gradation)
    b.dataset("ECO_MARK_LABEL", "Стадия развития", company.eco_mark)
    b.dataset(
        "OKFS_NAME", "Форма собственности", company.okfs_name.capitalize() if company.okfs_name else None
    )
    b.dataset("NEGATIVEMARK", "Признак ключевого собственника", company.negative_mark)

    # отношения с банком
    client_type = company.client_type
    b.dataset(
        "CL_TYPE", "Статус в банке", CLIENT_TYPES.get(client_type, client_type) if client_type else None
    )
    used = []
    for field, column, label, short in PRODUCTS:
        value = getattr(company, field)
        b.dataset(column, label, value)
        if value:
            used.append(short)
    known = [getattr(company, field) is not None for field, *_ in PRODUCTS]
    b.derived(
        "bank_products",
        "Продукты банка",
        used if any(known) else None,
        [f"feat:{column}" for _, column, *_ in PRODUCTS],
        display=", ".join(used) if used else "продуктами банка не пользуется",
        reason="нет данных о продуктах",
    )

    # ВЭД
    b.dataset("FTS_FLAG", "ВЭД по данным ФТС", company.fts_flag)
    if company.fts_countries:
        country_list = countries(company.fts_countries)
        b.dataset("FTS_COUNTRY_NAME", "Страны ВЭД", country_list, display=", ".join(country_list))
    elif company.fts_flag:
        b.missing.append(MissingFeature(id="feat:FTS_COUNTRY_NAME", label="Страны ВЭД"))

    # группа
    group = None
    if company.group_id:
        members = (group_members or [])[:GROUP_MEMBERS_SHOWN]
        group = CompanyGroup(id=company.group_id, size=max(group_size, 1), members=members)
        b.dataset(
            "GROUP_ID",
            "Группа компаний",
            company.group_id,
            display="компания вне группы" if group.size == 1 else f"{group.size} компаний в группе",
        )
    else:
        b.dataset("GROUP_ID", "Группа компаний", None)

    # регион
    b.dataset("REGION", "Регион", company.region)
    b.dataset("CITY", "Город", company.city)

    counterparties, payments = _counterparties(company, flows, b)

    if company.duplicates > 1:
        b.notes.append(
            f"id {company.id} встречается в выгрузке {company.duplicates} раз — взята первая запись"
        )

    return CompanyProfile(
        id=company.id,
        display_name=display_name(company, company.id),
        features=b.features,
        group=group,
        counterparties=counterparties,
        payments=payments,
        industry=industry,
        missing=b.missing,
        data_notes=b.notes,
    )


def _industry(industry: IndustryPosition | None, b: _Builder) -> None:
    sources = ["feat:MAINOKVED_CODE", "feat:REVENUE_COMPANY", "dataset"]
    if industry is None:
        b.derived("industry_rank", "Положение в отрасли", None, sources, reason="нет кода ОКВЭД или выручки")
        return
    b.derived(
        "industry_rank",
        "Положение в отрасли",
        f"№ {industry.rank} из {industry.total}",
        sources,
        display=(
            f"№ {industry.rank} из {industry.total} по выручке среди компаний с ОКВЭД {industry.okved}"
            f" в данных банка (№ {industry.class_rank} из {industry.class_total}"
            f" в классе {industry.okved_class})"
        ),
    )


def _side(pairs: list[tuple[float, CompanyRecord | None]]) -> PaymentSide:
    """Сторона оборота по парам (сумма, контрагент): доли по двузначным классам ОКВЭД и покрытие."""
    total = sum(amount for amount, _ in pairs)
    by_class: dict[str, list[float]] = defaultdict(list)
    for amount, cp in pairs:
        prefix = okved_prefix(cp.okved_code) if cp else None
        if prefix:
            by_class[prefix].append(amount)
    known = sum(sum(amounts) for amounts in by_class.values())
    sectors = [
        SectorShare(
            okved=prefix,
            sector=SECTOR_BY_CODE.get(prefix),
            amount=round(sum(amounts), 2),
            share=round(sum(amounts) / total, 4),
            counterparties=len(amounts),
        )
        for prefix, amounts in by_class.items()
    ]
    sectors.sort(key=lambda s: (-s.amount, s.okved))
    return PaymentSide(
        amount=round(total, 2),
        counterparties=len(pairs),
        coverage=round(known / total, 4) if total else 0.0,
        sectors=sectors,
    )


def _side_features(side: PaymentSide, name: str, label: str, of_what: str, b: _Builder) -> None:
    if not side.amount:
        b.derived(name, label, None, ["payments"], reason=f"нет {of_what} от внешних контрагентов в выгрузке")
        return
    if not side.sectors:
        reason = f"отрасль неизвестна ни у одного из {side.counterparties} контрагентов: их нет в выгрузке"
        b.derived(name, label, None, ["payments"], reason=reason)
        return
    # одна отрасль может собираться из нескольких классов ОКВЭД
    by_sector: dict[str, float] = defaultdict(float)
    for s in side.sectors:
        by_sector[s.sector or f"ОКВЭД {s.okved}"] += s.share
    top = sorted(by_sector.items(), key=lambda item: -item[1])[:5]
    b.derived(
        name,
        label,
        [f"{sector} — {format_share(share)}" for sector, share in top],
        ["payments", "feat:MAINOKVED_CODE"],
        display=(
            f"{format_rub(side.amount)} от {side.counterparties} контрагентов;"
            f" отрасль известна у {format_share(side.coverage)} суммы"
        ),
    )


def _counterparties(
    company: CompanyRecord, flows: list[Flow], b: _Builder
) -> tuple[list[Counterparty], PaymentStructure | None]:
    pairs: dict[str, _Pair] = defaultdict(_Pair)
    self_payments = 0
    outliers: set[str] = set()  # контрагенты, у которых отброшена хотя бы одна сторона
    for flow in flows:
        if flow.counterparty_id == company.id:
            self_payments += 1
            continue
        if company.revenue and flow.amount > company.revenue * OUTLIER_REVENUE_RATIO:
            outliers.add(flow.counterparty_id)
            continue
        if flow.amount <= 0:
            continue
        pair = pairs[flow.counterparty_id]
        if flow.direction == "out":
            pair.out_amount += flow.amount
        else:
            pair.in_amount += flow.amount
        pair.payments += flow.payments
        pair.counterparty = pair.counterparty or flow.counterparty

    if self_payments:
        b.notes.append("платежи компании самой себе не учитываются в контрагентах")
    if outliers:
        b.notes.append(
            f"отброшено контрагентов с суммой больше годовой выручки: {len(outliers)}"
            " — вероятно, внутренние переводы"
        )

    turnover = sum(p.out_amount + p.in_amount for p in pairs.values())
    sources = ["payments", "feat:REVENUE_COMPANY"]
    if not turnover:
        reason = "нет платежей в выгрузке" if not flows else "все платежи — самой себе или выбросы"
        for name, label in (
            ("payments_turnover", "Платёжный оборот"),
            ("top_counterparties", "Крупные контрагенты"),
            ("customer_sectors", "Отрасли покупателей"),
            ("supplier_sectors", "Отрасли поставщиков"),
        ):
            b.derived(name, label, None, sources, reason=reason)
        return [], None

    def in_group(cp: CompanyRecord | None) -> bool:
        return bool(cp and company.group_id and cp.group_id == company.group_id)

    intra = sum(p.out_amount + p.in_amount for p in pairs.values() if in_group(p.counterparty))
    external = [p for p in pairs.values() if not in_group(p.counterparty)]
    customers = _side([(p.in_amount, p.counterparty) for p in external if p.in_amount])
    suppliers = _side([(p.out_amount, p.counterparty) for p in external if p.out_amount])
    revenue_coverage = round(turnover / company.revenue, 4) if company.revenue else None
    structure = PaymentStructure(
        turnover=round(turnover, 2),
        counterparties=len(pairs),
        intra_group_amount=round(intra, 2),
        intra_group_share=round(intra / turnover, 4),
        customers=customers,
        suppliers=suppliers,
        revenue_coverage=revenue_coverage,
        excluded_self_payments=self_payments,
        excluded_outliers=len(outliers),
    )

    display = f"{format_rub(turnover)}, контрагентов: {len(pairs)}"
    if revenue_coverage is not None:
        display += f"; {format_share(revenue_coverage)} выручки"
    b.derived("payments_turnover", "Платёжный оборот", round(turnover, 2), sources, display=display)
    if revenue_coverage is not None and revenue_coverage < LOW_COVERAGE:
        b.notes.append(
            f"платежи в выгрузке — {format_share(revenue_coverage)} выручки: картина контрагентов неполная"
        )
    if intra:
        b.derived(
            "intra_group_share",
            "Оборот внутри группы",
            round(intra / turnover, 4),
            ["payments", "feat:GROUP_ID"],
            display=(
                f"{format_share(intra / turnover)} платёжного оборота"
                " — в отрасли покупателей и поставщиков не входит"
            ),
        )
    _side_features(customers, "customer_sectors", "Отрасли покупателей", "поступлений", b)
    _side_features(suppliers, "supplier_sectors", "Отрасли поставщиков", "платежей", b)

    ranked = sorted(pairs.items(), key=lambda item: (-(item[1].out_amount + item[1].in_amount), item[0]))
    result = []
    for cp_id, pair in ranked[:TOP_COUNTERPARTIES]:
        cp = pair.counterparty
        if pair.out_amount and pair.in_amount:
            role = "both"
        else:
            role = "supplier" if pair.out_amount else "customer"
        okved = None
        if cp and cp.okved_code:
            okved = f"{cp.okved_code} {cp.okved_name}" if cp.okved_name else cp.okved_code
        amount = pair.out_amount + pair.in_amount
        result.append(
            Counterparty(
                id=cp_id,
                display_name=display_name(cp, cp_id),
                in_dataset=cp is not None,
                okved=okved,
                sector=sector_for(cp.okved_code) if cp else None,
                role=role,
                amount=round(amount, 2),
                payments=pair.payments,
                share=round(amount / turnover, 4),
                intra_group=in_group(cp),
            )
        )

    b.derived(
        "top_counterparties",
        "Крупные контрагенты",
        [
            f"{c.id} · {_ROLE_NAMES[c.role]} · {c.sector or 'отрасль неизвестна'}"
            f" · {format_share(c.share)} оборота{' · в группе' if c.intra_group else ''}"
            for c in result
        ],
        sources,
    )
    return result, structure
