"""Эндпоинты агента: инсайт по событию, своя новость, уточняющий вопрос, трасса, отзывы."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from api.agent.ask import AskIn, AskOut
from api.agent.jobs import JobStatus
from api.agent.loop import AgentError, CompanyNotFound
from api.agent.ports import ParseError
from api.agent.service import AgentService, NotFound, NotRelevant
from api.agent.store import FeedbackIn, FeedbackOut, FeedbackStats
from api.contract import Insight, Statement, Trace
from api.llm import BudgetExceeded, LlmError

router = APIRouter(prefix="/api", tags=["агент"])


def get_agent(request: Request) -> AgentService:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "агент не запустился — подробности в логе API"
        )
    return agent


Agent = Annotated[AgentService, Depends(get_agent)]

NOT_RELEVANT = {204: {"description": "событие не касается компании пользователя"}}
BUILDING = {
    202: {
        "model": JobStatus,
        "description": "карточка собирается: статус с этапом; опрашивайте /api/insights/{event_id}/status",
    }
}
WAIT = Query(
    description="true — ждать готовую карточку в этом же запросе (до пары минут); false — сразу 202 и статус"
)


def _answer(result: Insight | JobStatus):
    """Готовая карточка — 200; сборка идёт — 202 со статусом."""
    if isinstance(result, JobStatus):
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result.model_dump(mode="json"))
    return result


UNAVAILABLE = {
    503: {"description": "модели недоступны или исчерпан суточный бюджет (Budget has been exceeded)"}
}


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound | CompanyNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, ParseError):
        return HTTPException(422, str(exc))
    if isinstance(exc, BudgetExceeded):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    if isinstance(exc, AgentError | LlmError):
        trace_id = getattr(getattr(exc, "trace", None), "id", None)
        detail = f"не удалось собрать карточку: {exc}" + (f" (трасса {trace_id})" if trace_id else "")
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    raise exc


@router.get(
    "/insights/{event_id}",
    response_model=Insight,
    responses={
        **BUILDING,
        **NOT_RELEVANT,
        404: {"description": "нет события или пользователя"},
        **UNAVAILABLE,
    },
)
def get_insight(
    event_id: str,
    agent: Agent,
    persona: Annotated[str, Query(description="id тестового пользователя, например p-u8318-cfo")],
    refresh: Annotated[bool, Query(description="пересобрать, не брать из кэша")] = False,
    wait: Annotated[bool, WAIT] = True,
    cached: Annotated[
        bool,
        Query(description="только готовый из кэша: не собран — 204 и X-Insight: not-built, без сборки"),
    ] = False,
):
    """Инсайт по паре «событие × пользователь». Готов — 200 из кэша; нет — сборка: с `wait=false` в фоне и
    сразу 202 со статусом (повторный запрос во время сборки новую не запускает). С `cached=true` сборка не
    запускается и модели не вызываются: экран показывает только уже собранные карточки."""
    if cached:
        try:
            ready = agent.ready(event_id, persona)
        except Exception as exc:
            raise _fail(exc) from exc
        if ready is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"X-Insight": "not-built"})
        return ready
    try:
        return _answer(agent.insight(event_id, persona, refresh=refresh, wait=wait))
    except NotRelevant:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise _fail(exc) from exc


class AnalyzeIn(BaseModel):
    persona_id: str
    text: str | None = Field(default=None, max_length=20000, description="текст новости")
    url: str | None = Field(default=None, max_length=2000, description="ссылка на новость")

    @model_validator(mode="after")
    def _one_of(self):
        if not (self.text and self.text.strip()) and not self.url:
            raise ValueError("нужен текст новости или ссылка")
        return self


@router.get(
    "/insights/{event_id}/status",
    response_model=JobStatus,
    responses={404: {"description": "сборка не запускалась или нет пользователя"}},
)
def insight_status(
    event_id: str,
    agent: Agent,
    persona: Annotated[str, Query(description="id тестового пользователя")],
) -> JobStatus:
    """Как идёт сборка карточки: этап, пройденные этапы, прошло и примерно осталось секунд. done — карточка
    готова (GET /api/insights/{event_id} вернёт 200), failed — текст ошибки, повторный GET начнёт заново."""
    try:
        return agent.status(event_id, persona)
    except Exception as exc:
        raise _fail(exc) from exc


@router.post(
    "/analyze",
    response_model=Insight,
    responses={**BUILDING, 422: {"description": "новость не разобрана"}, **UNAVAILABLE},
)
def analyze(body: AnalyzeIn, agent: Agent, wait: Annotated[bool, WAIT] = True):
    """Своя новость: текст или ссылка → разбор → инсайт. С `wait=false` сборка карточки — в фоне: 202 со
    статусом, в нём `event_id` новости для опроса /api/insights/{event_id}/status."""
    try:
        return _answer(agent.analyze(body.persona_id, body.text, body.url, wait=wait))
    except Exception as exc:
        raise _fail(exc) from exc


@router.post(
    "/insights/{insight_id}/ask",
    response_model=AskOut,
    responses={404: {"description": "нет инсайта"}, **UNAVAILABLE},
)
def ask(insight_id: str, body: AskIn, agent: Agent) -> AskOut:
    """Уточняющий вопрос по карточке: ответ с происхождением и источниками; вопрос не по теме — вежливый
    отказ."""
    try:
        return agent.ask(insight_id, body.question)
    except Exception as exc:
        raise _fail(exc) from exc


class ScenariosIn(BaseModel):
    debt_rub: float | None = Field(default=None, ge=0, description="ваш долг, ₽")
    fx_rub: float | None = Field(default=None, ge=0, description="валютные расчёты за год, ₽")
    purchases_rub: float | None = Field(
        default=None, ge=0, description="закупки за год, ₽ (например, топливо)"
    )


class ScenariosOut(BaseModel):
    scenarios: list[Statement] = Field(
        description="сценарии в рублях на ваших числах; нет числа — на единицу"
    )


@router.post(
    "/insights/{insight_id}/scenarios",
    response_model=ScenariosOut,
    responses={404: {"description": "нет инсайта"}},
)
def scenarios(insight_id: str, body: ScenariosIn, agent: Agent) -> ScenariosOut:
    """Пересчитать рубли карточки на своих числах: долг, валютные расчёты, закупки. Без модели, сразу."""
    from api.agent.scenarios import Inputs

    try:
        found = agent.scenarios(
            insight_id, Inputs(debt=body.debt_rub, fx=body.fx_rub, purchases=body.purchases_rub)
        )
    except Exception as exc:
        raise _fail(exc) from exc
    return ScenariosOut(scenarios=found)


@router.get("/traces/{trace_id}", response_model=Trace, responses={404: {"description": "нет трассы"}})
def get_trace(trace_id: str, agent: Agent) -> Trace:
    """Трасса агента: план, вызовы инструментов, модели (токены и стоимость), проверки и доработки."""
    trace = agent.store.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"трасса {trace_id} не найдена")
    return trace


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def post_feedback(body: FeedbackIn, agent: Agent) -> FeedbackOut:
    """Отзыв «полезно / не полезно» с причиной (критерий 12)."""
    if agent.store.get_insight(body.insight_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"инсайт {body.insight_id} не найден")
    return agent.store.add_feedback(body)


@router.get("/feedback/stats", response_model=FeedbackStats)
def feedback_stats(
    agent: Agent, insight_id: Annotated[str | None, Query(description="только по одному инсайту")] = None
) -> FeedbackStats:
    """Сколько отзывов, доля «полезно», причины «не полезно» — основа мониторинга качества."""
    return agent.store.feedback_stats(insight_id)
