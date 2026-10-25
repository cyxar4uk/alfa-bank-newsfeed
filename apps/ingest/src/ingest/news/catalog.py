"""Каталог источников для бизнеса (`catalog.toml`): подключённые ленты и то, что можно подключить по договору или API.

`connected` и `icon_url` не хранятся в файле: источник подключён, если в `sources.toml` включена хотя бы одна его
лента; значок — у первой его ленты, где он задан.
"""

import tomllib
from importlib import resources
from typing import Literal

from pydantic import BaseModel, Field

from ingest.models import Reliability
from ingest.news.fetch import Feed, load_feeds


class CatalogSource(BaseModel):
    id: str
    name: str
    country: Literal["ru", "intl"]
    kind: Literal["free", "paid_api"]
    reliability: Reliability
    topics: list[str] = Field(default_factory=list)
    # для руководителя: что это за источник, что даст подключение, бесплатно или по подписке
    about: str = Field(min_length=1)
    benefit: str = Field(min_length=1)
    access: str = Field(min_length=1)
    industries: list[str] = Field(
        default_factory=list, description="префиксы ОКВЭД, для которых источник особенно полезен; пусто — для всех"
    )
    connected: bool = False
    how_to_connect: list[str] = Field(min_length=1)
    docs_url: str | None = None
    icon_url: str | None = Field(default=None, description="значок издания — из его ленты в sources.toml")
    feeds: list[str] = Field(default_factory=list, description="id лент из sources.toml")
    key_env: str | None = Field(default=None, description="куда на сервере кладут ключ платного API (.env)")
    note: str | None = Field(
        default=None,
        description="ограничение для руководителя («сейчас недоступно в России»); техника — в how_to_connect",
    )


def load_catalog(path: str | None = None, feeds: list[Feed] | None = None) -> list[CatalogSource]:
    if path:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = tomllib.loads(resources.files("ingest.news").joinpath("catalog.toml").read_text("utf-8"))
    by_id = {f.id: f for f in (feeds if feeds is not None else load_feeds())}
    out, seen = [], set()
    for raw in data.get("source", []):
        item = CatalogSource.model_validate(raw)
        if item.id in seen:
            raise ValueError(f"каталог: источник {item.id} указан дважды")
        unknown = [f for f in item.feeds if f not in by_id]
        if unknown:
            raise ValueError(f"каталог: у источника {item.id} нет лент {unknown} в sources.toml")
        seen.add(item.id)
        icon = next((by_id[f].icon for f in item.feeds if by_id[f].icon), None)
        connected = any(by_id[f].enabled for f in item.feeds)
        out.append(item.model_copy(update={"connected": connected, "icon_url": item.icon_url or icon}))
    return out
