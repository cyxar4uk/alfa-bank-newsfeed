"""Ограниченный второй шаг платежных связей через крупнейших внешних контрагентов."""

import math
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from api.chain import MIN_SHARE
from api.okved import SECTOR_BY_CODE, okved_prefix
from api.profile import aggregate_flows
from api.records import Flow

if TYPE_CHECKING:
    from api.repo import CompanyRepo

MAX_INTERMEDIARIES = 5
MAX_PATHS = 10
LIMITATION = (
    "Связь показывает только наблюдаемые платежи в данных банка и не доказывает зависимость, причинность, "
    "валюту, вероятность события или возможный убыток. Произведение долей — лишь условный индекс связи."
)


class IndirectPath(BaseModel):
    company_id: str
    intermediary_id: str
    counterparty_id: str
    first_amount: float = Field(ge=0, allow_inf_nan=False)
    first_share: float = Field(ge=0, le=1, allow_inf_nan=False)
    second_amount: float = Field(ge=0, allow_inf_nan=False)
    second_share: float = Field(ge=0, le=1, allow_inf_nan=False)
    conditional_link_index: float = Field(ge=0, le=1, allow_inf_nan=False)
    direction: str
    industry: str | None = None
    coverage: float = Field(ge=0, le=1, allow_inf_nan=False)
    limitation: str = LIMITATION


class IndirectDependencies(BaseModel):
    company_id: str
    paths: list[IndirectPath]
    intermediaries_checked: int = Field(ge=0, le=MAX_INTERMEDIARIES)
    limitation: str = LIMITATION


def _finite_flows(flows: list[Flow]) -> list[Flow]:
    """Отбрасывает некорректные суммы до агрегации, чтобы NaN/Inf не попали в знаменатели и JSON."""
    return [
        flow
        for flow in flows
        if flow.direction in {"in", "out"} and math.isfinite(flow.amount) and flow.amount > 0
    ]


def _side(pair, direction: str) -> float:
    return pair.in_amount if direction == "in" else pair.out_amount


def indirect_dependencies(
    repo: "CompanyRepo", company_id: str, okved: list[str] | None = None
) -> IndirectDependencies | None:
    """Пути in→in и out→out. Один root-read + максимум пять уникальных посредников и не более 10 путей."""
    company = repo.get_company(company_id)
    if company is None:
        return None
    aggregate = aggregate_flows(company, _finite_flows(repo.flows(company.id)))
    direct = [
        pair
        for pair in aggregate.external()
        if pair.in_amount + pair.out_amount > 0 and pair.counterparty is not None
    ]
    direct.sort(key=lambda pair: (-(pair.in_amount + pair.out_amount), pair.counterparty.id))
    selected = direct[:MAX_INTERMEDIARIES]
    root_totals = {
        direction: sum(_side(pair, direction) for pair in aggregate.external()) for direction in ("in", "out")
    }
    paths: list[IndirectPath] = []
    read_ids: set[str] = set()
    wanted_okved = set(okved or [])

    for pair in selected:
        intermediary = pair.counterparty
        if intermediary is None:
            continue
        if company.group_id and intermediary.group_id == company.group_id:
            continue
        read_ids.add(intermediary.id)
        second = aggregate_flows(intermediary, _finite_flows(repo.flows(intermediary.id)))
        external = second.external()

        for direction in ("in", "out"):
            first_total = root_totals[direction]
            second_total = sum(_side(candidate, direction) for candidate in external)
            if first_total <= 0 or second_total <= 0:
                continue
            first_amount = _side(pair, direction)
            first_share = first_amount / first_total
            if first_share < MIN_SHARE:
                continue

            # Coverage — доля соответствующей стороны, у которой известен двузначный класс ОКВЭД.
            industry_known = sum(
                _side(candidate, direction)
                for candidate in external
                if candidate.counterparty and okved_prefix(candidate.counterparty.okved_code)
            )
            coverage = min(industry_known / second_total, 1.0)
            for candidate in external:
                amount = _side(candidate, direction)
                if amount <= 0:
                    continue
                target = candidate.counterparty
                # Обратный цикл остаётся в знаменателе, но не создаёт путь в числителе.
                if target is None or target.id in {company.id, intermediary.id}:
                    continue
                if company.group_id and target.group_id == company.group_id:
                    continue
                if intermediary.group_id and target.group_id == intermediary.group_id:
                    continue
                prefix = okved_prefix(target.okved_code)
                if wanted_okved and prefix not in wanted_okved:
                    continue
                second_share = amount / second_total
                if second_share < MIN_SHARE:
                    continue
                paths.append(
                    IndirectPath(
                        company_id=company.id,
                        intermediary_id=intermediary.id,
                        counterparty_id=target.id,
                        first_amount=round(first_amount, 2),
                        first_share=round(first_share, 4),
                        second_amount=round(amount, 2),
                        second_share=round(second_share, 4),
                        conditional_link_index=round(round(first_share, 4) * round(second_share, 4), 6),
                        direction=(
                            "поступления: контрагент → посредник → компания"
                            if direction == "in"
                            else "платежи: компания → посредник → контрагент"
                        ),
                        industry=SECTOR_BY_CODE.get(prefix) if prefix else None,
                        coverage=round(coverage, 4),
                    )
                )

    # Отбираем крупные доли обеих наблюдаемых связей; индекс-произведение не задаёт значимость.
    paths.sort(
        key=lambda path: (
            -min(path.first_share, path.second_share),
            -path.second_share,
            -path.first_share,
            path.intermediary_id,
            path.counterparty_id,
        )
    )
    return IndirectDependencies(
        company_id=company.id, paths=paths[:MAX_PATHS], intermediaries_checked=len(read_ids)
    )
