"""Продукты банка под событие — с названием, почему и ссылкой, чтобы кнопка менеджеру говорила, что обсуждать:
«Обсудить с менеджером: форвард на валютную выручку».

Продукт предлагается, когда главная причина события — фактор карты с силой не ниже средней и под него есть
продукт (каталог — `team/docs/alfa_products.md`, ссылки оттуда). Если продукт у компании уже подключён
(признак в данных банка), в «почему» — «проверьте условия», а не «подключите». Для «к сведению» продуктов нет.
Ставок и лимитов в текстах нет: для крупного бизнеса условия индивидуальные.
"""

from dataclasses import dataclass

from api.contract import BankProduct, ExposureMap, FeedItem
from api.records import CompanyRecord
from api.takeaway import main_reason

LEVELS_WITH_PRODUCTS = {"act", "watch"}
STRONG = {"high", "medium"}
NO_ADVICE_ROLES = {"chief_accountant"}  # главбуху предложения продуктов не показываем (как у агента)


@dataclass(frozen=True)
class Offer:
    code: str
    name: str
    why: str
    link: str
    feature: str | None = None  # признак компании «продукт уже есть»
    has_why: str = "Продукт у вас уже подключён — проверьте условия под новую ситуацию."
    when: str = ""  # слово в канале фактора, при котором уместно (пусто — всегда)


FX_LINK = "https://kurs.alfabank.ru/articles/kak-biznesu-menshe-zaviset-ot-kursa-valyut/"
OFFERS: dict[str, list[Offer]] = {
    "fx": [
        Offer(
            "fx_forward_revenue",
            "Форвард на валютную выручку",
            "Курс меняет рублёвую выручку от экспорта: форвард фиксирует курс будущих поступлений.",
            FX_LINK,
            when="экспорт",
        ),
        Offer(
            "fx_forward_payments",
            "Форвард на валютные платежи",
            "Курс меняет рублёвую стоимость импорта: форвард фиксирует курс будущих платежей.",
            FX_LINK,
            when="импорт",
        ),
        Offer(
            "fx_forward",
            "Хеджирование валютных рисков",
            "Курс влияет на ваши расчёты с зарубежными партнёрами: обсудите форвард или опцион.",
            FX_LINK,
        ),
    ],
    "rate": [
        Offer(
            "debt_structure",
            "Структура долга и рефинансирование",
            "Высокая ставка дольше удорожает долг: обсудите структуру, рефинансирование или отсрочку.",
            "https://alfabank.ru/sme/profits/kredit-dlya-ooo/",
            feature="credit",
            has_why="Ваш кредит в банке — проверьте условия и срок пересмотра ставки.",
        )
    ],
    "deposit_yield": [
        Offer(
            "deposit",
            "Депозит для бизнеса",
            "Пока ставка высокая, свободные деньги можно разместить с фиксацией дохода.",
            "https://alfabank.ru/sme/deposits/",
            feature="deposit",
            has_why="Ваши размещения в банке — проверьте сроки под ожидаемое снижение ставки.",
        )
    ],
    "gov": [
        Offer(
            "guarantee",
            "Банковские гарантии",
            "Гарантия позволит участвовать в торгах, не замораживая оборотные средства.",
            "https://alfabank.ru/corporate/credit/garanty/",
            feature="guarantee",
            has_why="Проверьте лимит ваших гарантий под новые торги.",
        )
    ],
    "ved_logistics": [
        Offer(
            "ved",
            "Валютный контроль и ВЭД",
            "Менеджер ВЭД поможет с платёжным маршрутом и валютным контролем.",
            "https://alfabank.ru/corporate/ved/currency_control/vedomost/",
        )
    ],
}
FACTORING = Offer(
    "factoring",
    "Факторинг",
    "Банк заплатит за отгрузку сразу и заберёт отсрочку покупателя на себя.",
    "https://alfabank.ru/news/t/release/tsifrovie-resheniya-obespechili-alfa-banku-vedushchie-pozitsii-na-rinke-faktoringa/",
    feature="factoring",
    has_why="Проверьте лимит факторинга по покупателям.",
)


def _factor_level(exposure: ExposureMap | None, code: str) -> tuple[str, str]:
    factor = next((f for f in exposure.factors if f.code == code), None) if exposure else None
    channel = factor.channel.text.casefold() if factor and factor.channel else ""
    return (factor.level if factor else "none"), channel


def products_for(
    item: FeedItem, role: str, company: CompanyRecord | None, exposure: ExposureMap | None
) -> list[BankProduct]:
    """Продукты под событие: по главной причине; пусто — для «к сведению», главбуха и слабой зависимости."""
    if role in NO_ADVICE_ROLES or item.takeaway is None or item.takeaway.level not in LEVELS_WITH_PRODUCTS:
        return []
    key, _ = main_reason(item)
    if key.startswith("chain:buyers"):
        offers, channel = [FACTORING], ""
    else:
        level, channel = _factor_level(exposure, key)
        if level not in STRONG:
            return []
        offers = OFFERS.get(key, [])
    chosen = [o for o in offers if not o.when or o.when in channel]
    if not chosen:
        return []
    offer = chosen[0]
    flag = getattr(company, offer.feature, None) if offer.feature and company else None
    has = flag is True
    if offer.feature == "credit" and flag is False:
        return []  # кредита в банке точно нет — «структуру долга» обсуждать не с чем
    why = offer.has_why if has else offer.why
    return [BankProduct(code=offer.code, name=offer.name, why=why, link=offer.link, owned=has)]


def attach_products(
    items: list[FeedItem], role: str, company: CompanyRecord | None, exposure: ExposureMap | None
) -> None:
    """Продукты для всей ленты — после уровней: «к сведению» без них."""
    for item in items:
        item.products = products_for(item, role, company, exposure)
