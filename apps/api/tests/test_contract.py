import pytest
from pydantic import ValidationError

from api.contract import Insight, Statement


def test_fact_and_bank_need_refs():
    with pytest.raises(ValidationError):
        Statement(text="Ставка 14 %", origin="fact")
    with pytest.raises(ValidationError):
        Statement(text="Банк ждёт снижения", origin="bank", refs=[])
    with pytest.raises(ValidationError):
        Statement(text="Кредит в банке", origin="data")
    assert Statement(text="Кредиты подорожают", origin="ai", confidence="low").refs == []
    # оценка и предложение продукта — без обязательных ссылок
    assert (
        Statement(text="Плюс 40 млн ₽ процентов в год", origin="estimate", confidence="medium").origin
        == "estimate"
    )
    assert Statement(text="Факторинг сократит разрыв", origin="offer").refs == []


def test_fact_confidence_is_high():
    s = Statement(text="Ставка 14 %", origin="fact", refs=["src:news:1"], confidence="low")
    assert s.confidence == "high"


def insight(**overrides) -> Insight:
    data = {
        "id": "ins:1",
        "event": {"title": "ЦБ сохранил ставку 14 %", "date": "2026-09-11"},
        "relevance": {"score": 0.86, "reason": "У компании кредиты", "refs": ["feat:CL_PRODUCT_LOA_MARK"]},
        "what_happened": [{"text": "Ставка 14 %", "origin": "fact", "refs": ["src:news:8f2a"]}],
        "why_it_matters": [
            {
                "text": "Кредиты не подешевеют",
                "origin": "ai",
                "refs": ["feat:CL_PRODUCT_LOA_MARK"],
                "confidence": "medium",
            }
        ],
        "bank_view": [
            {"text": "Снижение не раньше декабря", "origin": "bank", "refs": ["src:alfa:keyrate#p2"]}
        ],
        "actions": [
            {"text": "Проверить ковенанты", "kind": "question", "refs": ["feat:CL_PRODUCT_LOA_MARK"]}
        ],
        "sources": [
            {"id": "src:news:8f2a", "kind": "news", "title": "ЦБ сохранил ставку"},
            {"id": "src:alfa:keyrate", "kind": "alfa_analytics", "title": "Ключевая ставка", "page": 2},
        ],
        "features_used": ["feat:CL_PRODUCT_LOA_MARK"],
    }
    data.update(overrides)
    return Insight.model_validate(data)


def test_insight_refs_resolve():
    assert insight().unresolved_refs() == set()


def test_insight_reports_unresolved_refs():
    ins = insight(features_used=[])
    assert ins.unresolved_refs() == {"feat:CL_PRODUCT_LOA_MARK"}


def test_bank_view_only_bank():
    with pytest.raises(ValidationError):
        insight(bank_view=[{"text": "Ставка снизится", "origin": "ai"}])


def test_openapi_has_contract_models():
    from api.main import app

    schemas = app.openapi()["components"]["schemas"]
    assert {"CompanyProfile", "Feature", "Persona", "Counterparty", "Health"} <= set(schemas)
