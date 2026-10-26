from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "postgresql://newsfeed:newsfeed@127.0.0.1:5433/newsfeed"
    # каталог с данными кейса; CSV компаний ищутся в DATA_DIR/companies и в самом DATA_DIR
    data_dir: Path = Path("data/raw")
    # перезагрузить данные, даже если те же файлы уже загружены
    import_force: bool = False
    # снимок новостей — источник ленты, если базы новостей нет
    news_snapshot: Path = Path("data/demo/news_snapshot.jsonl")
    # сколько последних новостей рассматривать для ленты и за сколько дней
    feed_candidates: int = 500
    feed_days: int = 90
    # сколько событий верха ленты дополнительно оценивает модель (0 — не оценивать)
    feed_llm_top: int = 10
    # прогревать ленты и карту рисков демо-пользователей при старте и раз в 12 минут
    feed_warmup: bool = True
    # разбор заранее (api.precompute): карточки «важно»/«следить» демо-пользователей — до открытия
    precompute_enabled: bool = True
    precompute_budget_rub: float = 100.0  # свой суточный бюджет — часть общего LLM_DAILY_BUDGET_RUB
    precompute_per_hour: int = 20
    precompute_in_flight: int = 1  # одновременно в очереди агента (из 3); остальные места — пользователям
    precompute_every_s: int = 300
    precompute_watch: bool = True  # «следить» — пока потрачено меньше половины бюджета

    # модели организаторов: без ключа и адреса агент не запускается, остальное API работает
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    # шаг агента → модель, JSON: {"draft": "z-ai/glm-5.3-flash"}; не заданные шаги — по умолчанию из api.llm
    llm_models: dict[str, str] = {}
    # доп. параметры запроса по шагу, JSON: {"draft": {"thinking": {"type": "disabled"}}}
    llm_step_params: dict[str, dict] = {}
    # запасная модель, если основная недоступна у провайдера, JSON: {"google/gemma-4-26b-a4b-it": "..."}
    llm_fallbacks: dict[str, str] = {}
    # принимать любые id моделей провайдера, а не только шесть моделей кейса
    llm_allow_any_model: bool = False
    # свой суточный лимит сервиса, ₽ (у организаторов 500 ₽ на ключ всей команды, сброс в 03:00 МСК)
    llm_daily_budget_rub: float = 150.0
    # кэш ответов моделей и журнал вызовов
    llm_cache_dir: Path = Path("data/cache/llm")
    # кэш картинок новостей для прокси /api/img
    img_cache_dir: Path = Path("data/cache/img")
    llm_journal: Path = Path("data/cache/llm_calls.jsonl")
    llm_timeout: float = 180.0
    # снимок новостей для проверки (в репозитории), если в DATA_DIR/derived нет свежего news.jsonl
    news_snapshot: Path = Path("data/demo/news_snapshot.jsonl")


@lru_cache
def get_settings() -> Settings:
    return Settings()
