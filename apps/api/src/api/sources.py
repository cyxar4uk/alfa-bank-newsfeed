"""Каталог источников новостей для экрана «Источники»: что предлагаем подключить и что уже подключено.

Список — каталог парсера (`ingest.news.catalog.load_catalog`, `catalog.toml`): российские и зарубежные,
открытые и платные по API, с инструкцией подключения и переменной ключа. Без каталога (старая версия парсера)
— из его лент (`sources.toml`) с умолчаниями. Подключён — если парсер уже читает источник или пользователь
отметил его сам. Ключи API в прототипе не принимаем — только инструкция, куда ключ кладётся на сервере.
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


@lru_cache(maxsize=1)
def _parser_catalog() -> list[dict] | None:
    try:
        from ingest.news.catalog import load_catalog
    except ImportError:
        return None
    entries = []
    for s in load_catalog():
        entries.append(
            {
                "id": s.id,
                "name": s.name,
                "country": s.country,
                "kind": s.kind,
                "reliability": getattr(s, "reliability", None),
                "topics": list(getattr(s, "topics", None) or []),
                "how_to_connect": list(getattr(s, "how_to_connect", None) or []),
                "docs_url": getattr(s, "docs_url", None),
                "icon_url": getattr(s, "icon_url", None),
                "note": getattr(s, "note", None),
                "key_env": getattr(s, "key_env", None),
                "feeds": list(getattr(s, "feeds", None) or []),
                "connected": bool(getattr(s, "connected", False)),
            }
        )
    return entries


def catalog_entries() -> list[dict]:
    """Источники каталога: из каталога парсера, а без него — по одному на издателя из его лент."""
    parsed = _parser_catalog()
    if parsed is not None:
        return parsed
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
            "note": None,
            "key_env": env if kind == "paid_api" else None,
            "feeds": [feed["id"]],
            "connected": kind == "free",  # открытую ленту парсер уже читает
        }
    return list(entries.values())


def entry_id(source_id: str) -> str:
    """Id записи каталога по id любой её ленты («cbr-events» → запись Банка России)."""
    entries = catalog_entries()
    if any(e["id"] == source_id for e in entries):
        return source_id
    by_feed = next((e["id"] for e in entries if source_id in e["feeds"]), None)
    if by_feed:
        return by_feed
    publisher = next((f.get("publisher") for f in _feeds() if f["id"] == source_id), None)
    return next((e["id"] for e in entries if publisher and e["name"] == publisher), source_id)


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


PUBLIC = (
    "id",
    "name",
    "country",
    "kind",
    "reliability",
    "topics",
    "how_to_connect",
    "docs_url",
    "icon_url",
    "note",
)


def catalog(connections: Connections, persona_id: str) -> list[SourceEntry]:
    mine = connections.connected(persona_id)
    entries = sorted(
        catalog_entries(),
        key=lambda e: (not e["connected"], e["country"] != "ru", e["kind"] != "free", e["name"]),
    )
    return [
        SourceEntry(**{k: e[k] for k in PUBLIC}, connected=e["connected"] or e["id"] in mine) for e in entries
    ]


def connect_message(entry: dict) -> str:
    """Что дальше после отметки «подключён»: открытый — уже в ленте; платный — куда положить ключ."""
    if entry["kind"] == "free":
        if entry["connected"]:
            return "Источник подключён: его новости уже приходят в вашу ленту."
        return "Источник отмечен подключённым; парсер начнёт читать его ленту после обновления стенда."
    where = f" — переменная {entry['key_env']} в файле .env на сервере" if entry.get("key_env") else ""
    last = entry["how_to_connect"][-1] if entry["how_to_connect"] else ""
    text = f"Источник отмечен подключённым. Чтобы новости пошли в ленту, нужен ключ API{where}."
    return f"{text} {last}".strip()
