"""Одно приоритетное уточнение, выбранное по теме события."""


def clarification_questions(ctx=None, saved=None) -> list[str]:
    if ctx is None:
        return []
    from api.agent.topics import event_topics

    topics = event_topics(ctx.event)
    fx_topic = "fx" in topics
    rate_topic = "rate" in topics
    if fx_topic:
        needed = (
            "fx_revenue_month_rub",
            "fx_purchases_month_rub",
            "fx_currency",
            "fx_base_rate",
            "fx_scenario_rate",
        )
        if saved is None or any(getattr(saved, key, None) is None for key in needed):
            return [
                "Чтобы сравнить валютные потоки за месяц, укажите поступления и закупки "
                "(для отсутствующей стороны — 0), валюту, базовый и сценарный курс."
            ]
    if rate_topic:
        if saved is not None and getattr(saved, "debt_rub", None) == 0:
            return []
        if saved is None or getattr(saved, "rate_type", None) is None:
            return [
                "Какой у вас долг, ставка по нему плавающая или фиксированная, и какие "
                "текущую и сценарную ставки взять для сравнения?"
            ]
        if getattr(saved, "rate_type", None) == "fixed":
            return []
        needed = ("debt_rub", "current_rate_pct", "scenario_rate_pct")
        if any(getattr(saved, key, None) is None for key in needed):
            return [
                "Для расчёта изменения годовых процентов укажите сумму долга, "
                "текущую ставку по договору и сценарную ставку."
            ]
    return []
