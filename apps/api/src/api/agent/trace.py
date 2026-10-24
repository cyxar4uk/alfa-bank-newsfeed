"""Трасса агента: каждый шаг — план, инструмент, вызов модели, проверка, доработка (критерий 11)."""

import uuid

from api.contract import Trace, TraceStep
from api.llm import CallRecord

STEP_LABELS = {
    "plan": "план",
    "draft": "черновик инсайта",
    "revise": "доработка черновика",
    "ask": "ответ на уточняющий вопрос",
}


def new_trace_id() -> str:
    return f"tr:{uuid.uuid4().hex[:16]}"


class TraceRecorder:
    def __init__(self, trace_id: str | None = None) -> None:
        self.trace = Trace(id=trace_id or new_trace_id())

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
