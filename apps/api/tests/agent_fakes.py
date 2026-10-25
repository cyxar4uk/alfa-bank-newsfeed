"""Подделки для тестов агента: компания, библиотека материалов, модель с заготовленными ответами."""

import datetime as dt
import json
import re

from factories import make_company

from api.agent.drafts import (
    Draft,
    DraftAction,
    DraftBankPosition,
    DraftStatement,
    DraftVerdict,
    Plan,
    PlanFactor,
)
from api.agent.ports import (
    AnalyticsHit,
    Chain,
    ChainCounterparty,
    Channel,
    Event,
    ExposureFactor,
    FactorTag,
    ParseError,
    SectorTag,
)
from api.contract import Persona, Source, SourceTags
from api.llm import Budget, Journal, LlmClient, TransportResponse
from api.profile import build_profile
from api.records import Flow

MSK = dt.timezone(dt.timedelta(hours=3))
NEWS_ID = "src:news:rate1"
PAGE = "src:alfa:keyrate-2026-09#p1"
FRAGMENT = "src:alfa:keyrate-2026-09#p1-6"
PAGE2 = "src:alfa:keyrate-2026-09#p2"

NEWS_TEXT = (
    "Совет директоров Банка России 11 сентября сохранил ключевую ставку на уровне 14% годовых. "
    "Снижение ставки не рассматривалось."
)
BANK_PAGE = (
    "Мы ожидаем сохранения паузы на заседании 23 октября: С учетом риторики ЦБ РФ мы меняем наш взгляд на\n"
    "динамику ключевой ставки на этот год. Если раньше мы ориентировались на ставку на уровне 13,5% на "
    "конец\n"
    "2026 г., то теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года. При этом наш "
    "прогноз по ставке на конец 2027 г. остается на уровне 12,0%."
)
BANK_TABLE = "Ставка, конец года, % | 16,0% | 14,0% | 12,0%"

PERSONA = Persona(
    id="p-u1-cfo",
    company_id="U_1",
    role="cfo",
    role_label="Финансовый директор",
    name="Финдиректор · Оптовик топлива",
    company_name="Оптовик топлива",
)


def make_profile():
    company = make_company()
    restaurant = make_company(
        id="U_2", okved_code="56.10", okved_name="Деятельность ресторанов", revenue=5e8, group_id=None
    )
    flows = [Flow("U_2", "in", 4e9, 50, restaurant), Flow("U_3", "out", 2e9, 10, None)]
    return build_profile(company, flows, group_size=3, group_members=["U_5", "U_6"])


def make_event(**overrides) -> Event:
    source = Source(
        id=NEWS_ID,
        kind="news",
        title="ЦБ сохранил ключевую ставку 14%",
        publisher="Интерфакс",
        published_at=dt.datetime(2026, 9, 11, 13, 30, tzinfo=MSK),
        fragment=overrides.pop("text", NEWS_TEXT),
        tags=SourceTags(okved=overrides.pop("okved", [])),
    )
    return Event(
        source=source,
        factors=overrides.pop("factors", [FactorTag(code="rate", strength=1.0)]),
        sectors=overrides.pop("sectors", []),
    )


EXPOSURE = [
    ExposureFactor(
        code="rate",
        label="стоимость заёмных денег",
        level="high",
        strength=0.7,
        channel_text="через собственный кредит",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
    ),
    ExposureFactor(
        code="fx",
        label="курс валют",
        level="medium",
        strength=0.6,
        channel_text="ВЭД: Китай, ОАЭ",
        refs=["feat:FTS_FLAG", "feat:FTS_COUNTRY_NAME"],
    ),
    ExposureFactor(
        code="demand_56",
        label="спрос покупателей · общепит",
        level="high",
        strength=1.0,
        channel_text="гостиницы и общепит: 100 % поступлений",
        refs=["feat:customer_sectors"],
        coverage=1.0,
    ),
]
CHAIN = Chain(
    channels=[
        Channel(
            kind="buyers",
            factor="demand_56",
            okved="56",
            sector="гостиницы и общепит",
            share=1.0,
            coverage=1.0,
            strength=1.0,
            text="гостиницы и общепит: 100 % поступлений, 1 контрагент",
            refs=["feat:customer_sectors"],
            counterparties=[
                ChainCounterparty(id="U_2", display_name="Компания №2 · рестораны", share=0.6667)
            ],
        )
    ]
)


class FakeCompany:
    def __init__(self, exposure=None, chain=None):
        self.profile_ = make_profile()
        self.exposure = EXPOSURE if exposure is None else exposure
        self.chain = CHAIN if chain is None else chain

    def persona(self, persona_id):
        return PERSONA if persona_id == PERSONA.id else None

    def profile(self, company_id):
        return self.profile_ if company_id == "U_1" else None

    def exposure_map(self, company_id):
        return self.exposure

    def counterparty_chain(self, company_id, event):
        return self.chain

    def group_impact(self, company_id, event):
        return None

    def relevance(self, persona, event):
        return None


class FakeLibrary:
    def __init__(self, events=None, page_texts=None):
        self.events = {e.id: e for e in (events or [make_event()])}
        self.pages = page_texts if page_texts is not None else {PAGE: BANK_PAGE, PAGE2: BANK_TABLE}
        self.queries: list[str] = []

    def get_event(self, event_id):
        return self.events.get(event_id)

    def search_news(self, query, *, factors=None, before=None, limit=5):
        return []

    def search_alfa_analytics(self, query, *, factors=None, limit=5, material=None):
        self.queries.append(query)
        return [
            AnalyticsHit(
                source=Source(
                    id=FRAGMENT,
                    kind="alfa_analytics",
                    title="Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%, риторика стала жестче",
                    publisher="Альфа-Банк",
                    page=1,
                    fragment=BANK_PAGE,
                ),
                page_ref=PAGE,
                material_date=dt.date(2026, 9, 11),
            )
        ]

    def alfa_page_text(self, ref):
        return self.pages.get(re.sub(r"(#p\d+)-\d+$", r"\1", ref))

    def parse_news(self, *, text=None, url=None):
        if not text or len(text) < 40:
            raise ParseError("слишком короткий текст")
        event = make_event(text=text, okved=["56"], sectors=[SectorTag(okved="56", name="общепит")])
        event.source.id = "src:news:user-1"
        self.events[event.id] = event
        return event


# --- черновики ------------------------------------------------------------------------------------


def fact(**kw) -> DraftStatement:
    base = dict(
        text="ЦБ 11 сентября сохранил ключевую ставку 14%.",
        origin="fact",
        refs=[NEWS_ID],
        quote="сохранил ключевую ставку на уровне 14% годовых",
    )
    return DraftStatement(**{**base, **kw})


def bank(**kw) -> DraftStatement:
    base = dict(
        text="Альфа-Банк в материале от 11.09.2026 ждёт сохранения ставки 14,0% до конца года.",
        origin="bank",
        refs=[FRAGMENT],
        quote="теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года",
    )
    return DraftStatement(**{**base, **kw})


def good_draft(**overrides) -> Draft:
    values = dict(
        relevance_reason="кредит компании и покупатели из общепита",
        relevance_refs=["feat:CL_PRODUCT_LOA_MARK"],
        what_happened=[fact()],
        why_it_matters=[
            DraftStatement(
                text="У компании кредит в банке.",
                origin="data",
                refs=["feat:CL_PRODUCT_LOA_MARK"],
                factor="rate",
            ),
            DraftStatement(
                text="Все поступления — от покупателей из общепита.",
                origin="data",
                refs=["feat:customer_sectors"],
                factor="demand_56",
            ),
            DraftStatement(
                text="Долг не подешевеет до конца года, а рестораны при дорогих деньгах сократят закупки.",
                origin="ai",
                refs=["feat:CL_PRODUCT_LOA_MARK", "feat:customer_sectors"],
                confidence="medium",
                factor="rate",
            ),
        ],
        risks=[
            DraftStatement(
                text="Процентные расходы останутся высокими до конца года.",
                origin="ai",
                refs=["feat:CL_PRODUCT_LOA_MARK"],
                confidence="high",
                factor="rate",
            ),
            DraftStatement(
                text="Покупатели из общепита могут растянуть оплату.",
                origin="ai",
                refs=["feat:customer_sectors"],
                confidence="medium",
                factor="demand_56",
            ),
        ],
        opportunities=[],
        watch=[],
        bank_view=[bank()],
        actions=[
            DraftAction(text="Какая доля долга — по плавающей ставке?", kind="question"),
            DraftAction(text="Сценарий ликвидности при задержке оплат ресторанов.", kind="scenario"),
        ],
        verdict=DraftVerdict(
            level="act",
            headline="Для вас важно: кредит не подешевеет до конца года",
            why="Ставка осталась 14% — процентные расходы по вашему кредиту не снизятся.",
            actions=[
                {
                    "text": "Проверьте, какая доля долга — по плавающей ставке",
                    "owner": "финансовой службе",
                    "due": "на неделе",
                }
            ],
            refs=["feat:CL_PRODUCT_LOA_MARK"],
        ),
        bank_position=DraftBankPosition(
            statement="Альфа-Банк ожидает сохранения ставки 14,0% до конца года.",
            refs=[FRAGMENT],
            quote="теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года",
        ),
    )
    values.update(overrides)
    return Draft(**values)


GOOD_PLAN = Plan(
    factors=[PlanFactor(code="rate", why="кредит"), PlanFactor(code="demand_56", why="покупатели")],
    channels=["direct", "buyers"],
    analytics_queries=["ключевая ставка прогноз"],
    news_queries=[],
    need_estimates=True,
    role_focus="стоимость долга",
)


# --- модель ---------------------------------------------------------------------------------------


def reply(obj, cost=0.1) -> TransportResponse:
    content = obj if isinstance(obj, str) else json.dumps(obj.model_dump(mode="json"), ensure_ascii=False)
    data = {
        "model": "deepseek/deepseek-v4.1-flash",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 300, "cost": cost},
    }
    return TransportResponse(200, data, json.dumps(data))


class ScriptedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def post(self, body):
        self.bodies.append(body)
        if not self.responses:
            raise AssertionError("модель вызвана больше, чем ожидалось")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_llm(transport, limit=100.0) -> LlmClient:
    return LlmClient(
        transport, budget=Budget(limit), journal=Journal(None), cache=None, sleep=lambda s: None, fallbacks={}
    )
