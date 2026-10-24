"""Каталог источников новостей для экрана «Источники»: что предлагаем подключить и что уже подключено.

Список — из лент парсера (`ingest/news/sources.toml`): издатель, надёжность, домены. Поля, которых в ленте
нет, заполняются по умолчанию: открытая лента (kind = free) подключена всем — парсер её уже читает; платный
сервис (kind = paid_api) подключается пользователем. Ключи API в прототипе не принимаем — только инструкция,
куда ключ кладётся на сервере.
"""

import tomllib
from functools import lru_cache
from importlib import resources
from typing import Protocol

from psycopg_pool import ConnectionPool

from api.contract import SourceEntry

FREE_STEPS = ["Открытая лента: новости уже приходят в вашу ленту, подключать ничего не нужно."]
PAID_STEPS = [
    "Оформите подписку на сервис и получите ключ API в личном кабинете сервиса.",
    "Передайте ключ администратору стенда: ключ кладётся на сервере в файл .env (переменная {env}),"
    " в интерфейс его вводить не нужно.",
    "После перезапуска парсера новости сервиса появятся в ленте.",
]
INTL_SUFFIXES = (".com", ".org", ".net", ".io", ".uk", ".eu", ".de", ".cn", ".co")


@lru_cache(maxsize=1)
def _feeds() -> list[dict]:
    raw = resources.files("ingest.news").joinpath("sources.toml").read_text("utf-8")
    return tomllib.loads(raw).get("feed", [])


def _country(feed: dict) -> str:
    if feed.get("country") in ("ru", "intl"):
        return feed["country"]
    hosts = feed.get("hosts") or []
    return "intl" if hosts and all(h.endswith(INTL_SUFFIXES) for h in hosts) else "ru"


def catalog_entries() -> list[dict]:
    """Источники каталога — по одному на издателя: у Банка России две ленты, в каталоге он один."""
    entries: dict[str, dict] = {}
    for feed in _feeds():
        if feed.get("enabled") is False:
            continue  # выключен из-за условий использования или недоступности
        name = feed.get("publisher") or feed["id"]
        if name in entries:
            continue
        kind = feed.get("kind") if feed.get("kind") in ("free", "paid_api") else "free"
        env = f"SOURCE_{feed['id'].upper().replace('-', '_')}_API_KEY"
        entries[name] = {
            "id": feed["id"],
            "name": name,
            "country": _country(feed),
            "kind": kind,
            "reliability": feed.get("reliability"),
            "topics": list(feed.get("topics") or []),
            "how_to_connect": list(
                feed.get("how_to_connect")
                or (FREE_STEPS if kind == "free" else [s.format(env=env) for s in PAID_STEPS])
            ),
            "docs_url": feed.get("docs_url"),
            "icon_url": feed.get("icon_url"),
        }
    return list(entries.values())


def entry_id(source_id: str) -> str:
    """Id записи каталога по id любой ленты издателя («cbr-events» → «cbr-press»)."""
    publisher = next((f.get("publisher") for f in _feeds() if f["id"] == source_id), None)
    if publisher is None:
        return source_id
    return next((e["id"] for e in catalog_entries() if e["name"] == publisher), source_id)


class Connections(Protocol):
    def connected(self, persona_id: str) -> set[str]: ...

    def connect(self, persona_id: str, source_id: str) -> None: ...


class MemoryConnections:
    def __init__(self) -> None:
        self._by_persona: dict[str, set[str]] = {}

    def connected(self, persona_id: str) -> set[str]:
        return set(self._by_persona.get(persona_id, set()))

    def connect(self, persona_id: str, source_id: str) -> None:
        self._by_persona.setdefault(persona_id, set()).add(source_id)


class PgConnections:
    """Отметки «подключён» — таблица source_connections (api.db)."""

    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def connected(self, persona_id: str) -> set[str]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT source_id FROM source_connections WHERE persona_id = %s", (persona_id,)
            ).fetchall()
        return {r[0] for r in rows}

    def connect(self, persona_id: str, source_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO source_connections (persona_id, source_id) VALUES (%s, %s)"
                " ON CONFLICT DO NOTHING",
                (persona_id, source_id),
            )


def catalog(connections: Connections, persona_id: str) -> list[SourceEntry]:
    mine = connections.connected(persona_id)
    return [
        SourceEntry(**e, connected=e["kind"] == "free" or e["id"] in mine)
        for e in sorted(
            catalog_entries(), key=lambda e: (e["country"] != "ru", e["kind"] != "free", e["name"])
        )
    ]
