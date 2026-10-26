"""Чистая математика пользовательских сценариев."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FxFlow:
    base_month_rub: float
    scenario_month_rub: float
    change_month_rub: float


def fx_flow(
    receipts_month_rub: float,
    purchases_month_rub: float,
    base_rate: float,
    scenario_rate: float,
) -> FxFlow:
    """Изменение рублёвого денежного потока; суммы за один месяц, не показатель прибыли."""
    net = receipts_month_rub - purchases_month_rub
    return FxFlow(net, net * scenario_rate / base_rate, net * (scenario_rate / base_rate - 1))


def interest_change(debt_rub: float, current_rate_pct: float, scenario_rate_pct: float) -> float:
    """Годовое изменение процентов при полной переоценке долга по новой ставке."""
    return debt_rub * (scenario_rate_pct - current_rate_pct) / 100
