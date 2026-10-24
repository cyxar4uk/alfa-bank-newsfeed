"""Эндпоинты агента: инсайт по событию, своя новость, уточняющий вопрос, трасса, отзывы."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator

from api.agent.ask import AskIn, AskOut
from api.agent.loop import AgentError, CompanyNotFound
from api.agent.ports import ParseError
from api.agent.service import AgentService, NotFound, NotRelevant
from api.agent.store import FeedbackIn, FeedbackOut, FeedbackStats
from api.contract import Insight, Trace
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
    responses={**NOT_RELEVANT, 404: {"description": "нет события или пользователя"}, **UNAVAILABLE},
)
def get_insight(
    event_id: str,
    agent: Agent,
    persona: Annotated[str, Query(description="id тестового пользователя, например p-u8318-cfo")],
    refresh: Annotated[bool, Query(description="пересобрать, не брать из кэша")] = False,
):
    """Инсайт по паре «событие × пользователь». Собирается при первом запросе, дальше — из кэша."""
    try:
        return agent.insight(event_id, persona, refresh=refresh)
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


@router.post(
    "/analyze",
    response_model=Insight,
    responses={422: {"description": "новость не разобрана"}, **UNAVAILABLE},
)
def analyze(body: AnalyzeIn, agent: Agent) -> Insight:
    """Своя новость: текст или ссылка → разбор → инсайт для пользователя."""
    try:
        return agent.analyze(body.persona_id, body.text, body.url)
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
