"""Версия логики агента — часть ключа кэша карточек.

Карточка, собранная со старыми промптами, моделями или правилами самопроверки, не должна показываться после
их смены: прогрев перед демо и кэш в БД иначе отдадут устаревшее. Версия — хэш того, что определяет карточку:
тексты промптов, схема черновика, список проверок, модели и параметры шагов.
"""

import hashlib
import json

from api.agent import checks, prompts, relevance
from api.agent.drafts import Draft
from api.contract import Insight

# поднимать вручную, если поведение изменилось так, что хэш этого не увидит (например, логика сборки)
LOGIC_REVISION = 1


def agent_version(models: dict[str, str] | None = None, step_params: dict[str, dict] | None = None) -> str:
    parts = {
        "revision": LOGIC_REVISION,
        "prompts": [prompts.PLAN_SYSTEM, prompts.DRAFT_SYSTEM, prompts.ASK_SYSTEM],
        "draft": Draft.model_json_schema(),
        "insight": Insight.model_json_schema(),
        "checks": list(checks.CHECKS),
        "relevance": relevance.AGENT_LINK_WEIGHT,
        "models": models or {},
        "params": step_params or {},
    }
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
