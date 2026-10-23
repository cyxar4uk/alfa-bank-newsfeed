from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://newsfeed:newsfeed@127.0.0.1:5433/newsfeed"
    # каталог с данными кейса; CSV компаний ищутся в DATA_DIR/companies и в самом DATA_DIR
    data_dir: Path = Path("data/raw")
    # перезагрузить данные, даже если те же файлы уже загружены
    import_force: bool = False

    # модели организаторов: без ключа и адреса агент не запускается, остальное API работает
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    # шаг агента → модель, JSON: {"draft": "z-ai/glm-5.3-flash"}; не заданные шаги — по умолчанию из api.llm
    llm_models: dict[str, str] = {}
    # доп. параметры запроса по шагу, JSON: {"draft": {"thinking": {"type": "disabled"}}}
    llm_step_params: dict[str, dict] = {}
    # свой суточный лимит сервиса, ₽ (у организаторов 500 ₽ на ключ всей команды, сброс в 03:00 МСК)
    llm_daily_budget_rub: float = 150.0
    # кэш ответов моделей и журнал вызовов
    llm_cache_dir: Path = Path("data/cache/llm")
    llm_journal: Path = Path("data/cache/llm_calls.jsonl")
    llm_timeout: float = 180.0
    # снимок новостей для проверки (в репозитории), если в DATA_DIR/derived нет свежего news.jsonl
    news_snapshot: Path = Path("data/demo/news_snapshot.jsonl")


@lru_cache
def get_settings() -> Settings:
    return Settings()
