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

from api.contract import ExposureMap, SourceEntry

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

    def disconnected(self, persona_id: str) -> set[str]: ...

    def connect(self, persona_id: str, source_id: str) -> None: ...

    def disconnect(self, persona_id: str, source_id: str) -> None: ...


class MemoryConnections:
    def __init__(self) -> None:
        self._by_persona: dict[str, dict[str, bool]] = {}

    def connected(self, persona_id: str) -> set[str]:
        return {s for s, on in self._by_persona.get(persona_id, {}).items() if on}

    def disconnected(self, persona_id: str) -> set[str]:
        return {s for s, on in self._by_persona.get(persona_id, {}).items() if not on}

    def connect(self, persona_id: str, source_id: str) -> None:
        self._by_persona.setdefault(persona_id, {})[source_id] = True

    def disconnect(self, persona_id: str, source_id: str) -> None:
        self._by_persona.setdefault(persona_id, {})[source_id] = False


class PgConnections:
    """Отметки «подключён» — таблица source_connections (api.db)."""

    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def _marked(self, persona_id: str, on: bool) -> set[str]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT source_id FROM source_connections WHERE persona_id = %s AND connected = %s",
                (persona_id, on),
            ).fetchall()
        return {r[0] for r in rows}

    def connected(self, persona_id: str) -> set[str]:
        return self._marked(persona_id, True)

    def disconnected(self, persona_id: str) -> set[str]:
        return self._marked(persona_id, False)

    def _mark(self, persona_id: str, source_id: str, on: bool) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO source_connections (persona_id, source_id, connected) VALUES (%s, %s, %s)"
                " ON CONFLICT (persona_id, source_id) DO UPDATE SET connected = EXCLUDED.connected,"
                " connected_at = now()",
                (persona_id, source_id, on),
            )

    def connect(self, persona_id: str, source_id: str) -> None:
        self._mark(persona_id, source_id, True)

    def disconnect(self, persona_id: str, source_id: str) -> None:
        self._mark(persona_id, source_id, False)


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
)  # `note` каталога парсера — заметки разработчиков («API нет, только RSS»): пользователю не отдаём

# источник → факторы карты, о которых он пишет больше всего: подключение полезно, если они у компании сильные
SOURCE_FACTORS = {
    "cbr": ("rate", "fx", "deposit_yield"),
    "nalog": ("tax_regulation",),
    "government": ("gov", "tax_regulation"),
    "rg": ("tax_regulation", "gov"),
    "moex": ("fx", "deposit_yield", "commodity_oil"),
    "cbonds": ("rate", "deposit_yield"),
    "prime": ("fx", "deposit_yield"),
    "reuters": ("commodity_oil", "commodity_agro", "commodity_metals", "fx", "ved_logistics"),
    "bloomberg": ("commodity_oil", "commodity_agro", "commodity_metals", "fx"),
    "ft": ("ved_logistics", "fx"),
}
STRONG = {"high", "medium"}


def _gives(e: dict, factors: list[str]) -> str:
    """Что даст подключение — одной фразой, без техники."""
    what = ", ".join(e["topics"][:3]) or "деловые новости"
    if factors:
        names = ", ".join(f[:1].lower() + f[1:] for f in factors)  # «ВЭД» в середине названия остаётся
        return f"Новости: {what} — о том, к чему чувствительна ваша компания ({names})."
    return f"Новости: {what}."


def catalog(
    connections: Connections, persona_id: str, exposure: ExposureMap | None = None
) -> list[SourceEntry]:
    mine, off = connections.connected(persona_id), connections.disconnected(persona_id)
    strong = {f.code: f.label for f in exposure.factors if f.level in STRONG} if exposure else {}
    out = []
    for e in catalog_entries():
        factors = [strong[c] for c in SOURCE_FACTORS.get(e["id"], ()) if c in strong]
        out.append(
            SourceEntry(
                **{k: e[k] for k in PUBLIC},
                connected=(e["connected"] or e["id"] in mine) and e["id"] not in off,
                relevant=bool(factors),
                gives=_gives(e, factors),
            )
        )
    # подключённые, потом полезные компании, свои, открытые
    return sorted(
        out, key=lambda s: (not s.connected, not s.relevant, s.country != "ru", s.kind != "free", s.name)
    )


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
