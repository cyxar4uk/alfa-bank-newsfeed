"""Тестовые пользователи: 1–2 роли на крупные компании разных отраслей.

Сначала — пользователи демо-клиентов сценария проверки: компании подобраны вручную под разные каналы
влияния (поставщики, покупатели, группа, ВЭД). Затем набор добирается до восьми компаний: по одной
из отраслей, на которых хорошо видно влияние новостей и аналитики банка, — действующий клиент
с наибольшей выручкой.
Набор детерминирован; компании, которой нет в загруженных данных, просто нет в списке.
"""

from api.contract import ROLE_LABELS, Persona
from api.okved import sector_for
from api.profile import company_number
from api.records import CompanyRecord

MAX_COMPANIES = 8

# компания, роль, подпись компании в интерфейсе (обезличенная: чем занимается и где)
DEMO_PERSONAS: list[tuple[str, str, str]] = [
    ("U_8318", "cfo", "Оптовик автозапчастей, Москва"),
    ("U_8318", "chief_accountant", "Оптовик автозапчастей, Москва"),
    ("U_57706", "owner", "Топливный оптовик, Москва (холдинг)"),
    ("U_57706", "treasury", "Топливный оптовик, Москва"),
    ("U_34911", "ceo", "Зернотрейдер, Ростов-на-Дону"),
    ("U_34911", "treasury", "Зернотрейдер, Ростов-на-Дону"),
    ("U_258116", "ceo", "Поставщик общепита, Москва"),
]

DEMO_COMPANIES = list(dict.fromkeys(company_id for company_id, *_ in DEMO_PERSONAS))

PREFERRED_SECTORS = [
    "оптовая торговля",
    "строительство",
    "автомобили",
    "транспорт и логистика",
    "энергетика",
    "розничная торговля",
    "недвижимость",
    "гостиницы и общепит",
]

# роли добранных компаний — по кругу
FILL_ROLES = ["cfo", "owner", "chief_accountant", "treasury", "ceo"]

ROLE_SHORT = {
    "owner": "Собственник",
    "ceo": "Гендиректор",
    "cfo": "Финдиректор",
    "chief_accountant": "Главбух",
    "treasury": "Казначей",
    "other": "Сотрудник",
}
_ROLE_ID = {
    "owner": "owner",
    "ceo": "ceo",
    "cfo": "cfo",
    "chief_accountant": "acc",
    "treasury": "tre",
    "other": "other",
}


def persona_id(company_id: str, role: str) -> str:
    return f"p-u{company_number(company_id)}-{_ROLE_ID[role]}"


def company_label(company: CompanyRecord) -> str:
    sector = sector_for(company.okved_code) or "компания"
    label = sector[0].upper() + sector[1:]
    place = company.city.removeprefix("г. ") if company.city else company.region
    return f"{label}, {place}" if place else label


def _persona(company: CompanyRecord, role: str, label: str) -> Persona:
    return Persona(
        id=persona_id(company.id, role),
        company_id=company.id,
        role=role,
        role_label=ROLE_LABELS[role],
        name=f"{ROLE_SHORT[role]} · {label}",
        company_name=label,
        sector=sector_for(company.okved_code),
    )


def pick_companies(
    companies: list[CompanyRecord], limit: int = MAX_COMPANIES, exclude_sectors: set[str] | None = None
) -> list[CompanyRecord]:
    """По компании из отрасли: действующие клиенты и крупнейшие — первыми, отрасли из приоритета — раньше."""
    ordered = sorted(companies, key=lambda c: (c.client_type != "CLIENT", -(c.revenue or 0), c.id))
    best: dict[str, CompanyRecord] = {}
    for company in ordered:
        sector = sector_for(company.okved_code)
        if sector is not None and sector not in best and sector not in (exclude_sectors or set()):
            best[sector] = company
    preferred = [best[s] for s in PREFERRED_SECTORS if s in best]
    rest = [c for s, c in best.items() if s not in PREFERRED_SECTORS]
    return (preferred + rest)[:limit]


def make_personas(companies: list[CompanyRecord]) -> list[Persona]:
    # сервис — для действующих клиентов: потенциальные и бывшие могут быть только контрагентами
    companies = [c for c in companies if c.client_type == "CLIENT"]
    by_id = {c.id: c for c in companies}
    personas = [
        _persona(by_id[company_id], role, label)
        for company_id, role, label in DEMO_PERSONAS
        if company_id in by_id
    ]
    demo = {p.company_id for p in personas}
    covered = {sector_for(by_id[company_id].okved_code) for company_id in demo} - {None}
    others = [c for c in companies if c.id not in demo]
    fill = pick_companies(others, limit=max(MAX_COMPANIES - len(demo), 0), exclude_sectors=covered)
    for i, company in enumerate(fill):
        personas.append(_persona(company, FILL_ROLES[i % len(FILL_ROLES)], company_label(company)))
    return personas
