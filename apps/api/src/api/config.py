from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://newsfeed:newsfeed@127.0.0.1:5433/newsfeed"
    # каталог с данными кейса; CSV компаний ищутся в DATA_DIR/companies и в самом DATA_DIR
    data_dir: Path = Path("data/raw")
    # перезагрузить данные, даже если те же файлы уже загружены
    import_force: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
