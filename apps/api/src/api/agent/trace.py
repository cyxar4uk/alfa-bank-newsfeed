"""Трасса агента: каждый шаг — план, инструмент, вызов модели, проверка, доработка (критерий 11)."""

import logging
import uuid
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from api.agent.plain import is_plain
from api.contract import Trace, TraceStep
from api.llm import CallRecord

STEP_LABELS = {
    "plan": "план",
    "draft": "черновик инсайта",
    "revise": "доработка черновика",
    "ask": "ответ на уточняющий вопрос",
}


# ход разбора, который видит пользователь, пока ждёт: инструмент → шаг человеческим языком
TOOL_STAGES = {
    "get_profile": "Смотрю, что известно о вашей компании",
    "get_exposure_map": "Разбираюсь, от чего зависит ваш бизнес",
    "get_counterparty_chain": "Смотрю, дойдёт ли это до вас через покупателей и поставщиков",
    "get_group_impact": "Смотрю, кому из вашей группы это важно",
    "search_alfa_analytics": "Ищу, что пишет об этом Альфа-Банк",
    "search_news": "Смотрю, что ещё пишут по теме",
    "estimate_rate_impact": "Считаю, сколько это в рублях",
    "get_products_for_risk": "Смотрю, чем может помочь банк",
}
MAX_FOUND = 6
log = logging.getLogger("api.agent.trace")


class ProgressStep(BaseModel):
    """Шаг хода разбора: что агент делает сейчас и что нашёл — для живой ленты «размышлений»."""

    title: str = Field(description="что делаю, человеческим языком")
    detail: str = Field(default="", description="пояснение к шагу")
    state: Literal["running", "done", "error"] = "running"
    found: list[str] = Field(default_factory=list, description="что нашёл: материал банка, цифры компании…")


def new_trace_id() -> str:
    return f"tr:{uuid.uuid4().hex[:16]}"


class TraceRecorder:
    def __init__(
        self,
        trace_id: str | None = None,
        on_progress: Callable[[list[ProgressStep]], None] | None = None,
    ) -> None:
        self.trace = Trace(id=trace_id or new_trace_id())
        self.on_progress = on_progress
        self.steps: list[ProgressStep] = []

    def _emit(self) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress([s.model_copy(deep=True) for s in self.steps])
        except Exception:  # ход разбора — вспомогательный: его сбой не роняет сборку
            log.exception("не передан ход разбора")

    def stage(self, title: str, detail: str = "") -> None:
        """Начался шаг разбора: предыдущий готов. Тот же шаг подряд не повторяем."""
        current = self.steps[-1] if self.steps else None
        if current is not None and current.title == title and current.state == "running":
            return
        for s in self.steps:
            if s.state == "running":
                s.state = "done"
        self.steps.append(ProgressStep(title=title, detail=detail))
        self._emit()

    def found(self, *items: str) -> None:
        """Что нашёл на текущем шаге; служебное (коды, «канал», «фактор») пользователю не показываем."""
        current = self.steps[-1] if self.steps else None
        if current is None:
            return
        added = False
        for item in items:
            item = (item or "").strip()[:160]
            if item and is_plain(item) and item not in current.found and len(current.found) < MAX_FOUND:
                current.found.append(item)
                added = True
        if added:
            self._emit()

    def finish(self, ok: bool = True) -> None:
        for s in self.steps:
            if s.state == "running":
                s.state = "done" if ok else "error"
        self._emit()

    @property
    def id(self) -> str:
        return self.trace.id

    def _add(self, **fields) -> TraceStep:
        step = TraceStep(n=len(self.trace.steps) + 1, **fields)
        self.trace.steps.append(step)
        return step

    def plan(self, summary: str) -> None:
        self._add(kind="plan", summary=summary)

    def tool(self, tool: str, args: dict, output_refs: list[str], summary: str) -> None:
        self._add(kind="tool", tool=tool, input=args, output_refs=output_refs[:50], summary=summary[:500])

    def llm(self, purpose: str, calls: list[CallRecord]) -> None:
        for call in calls:
            note = "из кэша" if call.cached else ("" if call.ok else (call.error or "ошибка"))
            self._add(
                kind="llm",
                model=call.model,
                purpose=STEP_LABELS.get(purpose, purpose)
                + (f" · попытка {call.attempt}" if call.attempt > 1 else ""),
                tokens_in=call.prompt_tokens,
                tokens_out=call.completion_tokens,
                cost_rub=round(call.cost, 4),
                summary=note or None,
            )

    def check(self, passed: bool, summary: str) -> None:
        self._add(kind="check", verdict="pass" if passed else "fail", summary=summary[:1500])

    def retry(self, summary: str) -> None:
        self._add(kind="retry", summary=summary[:500])

    @property
    def cost(self) -> float:
        return round(sum(s.cost_rub or 0 for s in self.trace.steps), 4)
