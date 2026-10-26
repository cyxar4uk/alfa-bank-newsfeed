"""Уточняющий вопрос по инсайту (критерий 9): ответ в контексте компании и события, с происхождением и
ссылками.

Контекст — тот же, что собрал агент для карточки (сохранён вместе с ней), плюс поиск по аналитике банка по
самому вопросу: так можно спросить «а что банк думает про курс?» и получить другой разрез. Ответ проходит ту
же самопроверку утверждений, что и карточка: без источника, с выдуманной цитатой или чужими цифрами — не
показываем.
"""

from pydantic import BaseModel, Field

from api.agent.checks import Checker
from api.agent.context import AgentContext, as_data, dumps
from api.agent.drafts import AskAnswer, cited, to_statement
from api.agent.prompts import ASK_SYSTEM
from api.agent.scenarios import SCENARIO_PREFIXES
from api.agent.tools import Tools
from api.agent.topics import RELATED, text_topics
from api.agent.trace import TraceRecorder
from api.contract import DISCLAIMER, Insight, Source, Statement
from api.llm import LlmClient

QUESTION_MAX = 1000


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=QUESTION_MAX)
    persona_id: str | None = None


class AskOut(BaseModel):
    insight_id: str
    question: str
    on_topic: bool
    answer: list[Statement] = Field(
        default_factory=list, description="ответ: утверждения с происхождением и ссылками"
    )
    refusal: str | None = None
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace_id: str
    disclaimer: str = DISCLAIMER


OFF_TOPIC = "Я отвечаю только на вопросы об этом событии и о том, как оно касается вашей компании."
NO_ANSWER = "Не нашёл, чем подтвердить ответ в данных компании и материалах по событию."


def _only_question(ctx: AgentContext, card: dict, question: str) -> None:
    """Ответ только на вопрос: расчёты и «мои числа» про другую тему модели не показываем."""
    asked = text_topics(question)
    for t in list(asked):
        asked |= RELATED.get(t, set())
    if not asked:
        return

    def related(text: str) -> bool:
        return bool(text_topics(text) & asked)

    ctx.estimates = [e for e in ctx.estimates if related(e.statement.text)]
    if not asked & {"rate", "deposit"}:
        ctx.user_inputs = None
    for place, items in card.get("consequences", {}).items():
        card["consequences"][place] = [
            st
            for st in items
            if not (st.get("origin") == "estimate" and st.get("text", "").startswith(SCENARIO_PREFIXES))
            or related(st.get("text", ""))
        ]


def answer(llm: LlmClient, tools: Tools, ctx: AgentContext, insight: Insight, question: str) -> AskOut:
    trace: TraceRecorder = tools.trace
    trace.plan(
        f"уточняющий вопрос к {insight.id}: ищу в аналитике банка по вопросу, отвечаю по контексту карточки"
    )
    tools.search_alfa_analytics(ctx, question)
    tools.load_pages(ctx, {h.page_ref for h in ctx.analytics})
    card = insight.model_dump(
        mode="json", include={"what_happened", "why_it_matters", "consequences", "bank_view"}
    )
    _only_question(ctx, card, question)
    messages = [
        {"role": "system", "content": ASK_SYSTEM},
        {
            "role": "user",
            "content": ctx.render()
            + "\n\nКарточка события, которую видит пользователь:\n"
            + dumps(card)
            + "\n\nВопрос пользователя:\n"
            + as_data("question", question),
        },
    ]
    completion = llm.complete("ask", messages, schema=AskAnswer, max_tokens=3000)
    trace.llm("ask", completion.calls)
    reply = completion.value
    if not reply.on_topic:
        trace.check(True, "вопрос не по теме — вежливый отказ")
        return AskOut(
            insight_id=insight.id,
            question=question,
            on_topic=False,
            refusal=reply.refusal or OFF_TOPIC,
            trace_id=trace.id,
        )

    checker = Checker(ctx)
    kept, problems = [], []
    for i, s in enumerate(reply.statements):
        issues = [x for x in checker.statement("answer", i, s) if x.hard]
        if issues:
            problems += [f"answer[{i}]: {x.message}" for x in issues]
        else:
            kept.append(s)
    trace.check(not problems, "; ".join(problems) or "все утверждения ответа подтверждены")

    sources = ctx.sources()
    used: dict[str, Source] = {}
    for s in kept:
        for ref in cited(s):
            src = sources.get(ref) or sources.get(ref.split("#", 1)[0])
            if src is not None:
                used.setdefault(src.id, src)
    warnings = []
    if problems:
        warnings.append(f"убрано утверждений без подтверждения: {len(reply.statements) - len(kept)}")
    statements = [to_statement(s) for s in kept]
    return AskOut(
        insight_id=insight.id,
        question=question,
        on_topic=True,
        answer=statements,
        refusal=None if statements else NO_ANSWER,
        sources=list(used.values()),
        warnings=warnings,
        trace_id=trace.id,
    )
