"""Каталог источников новостей для экрана «Источники»: что предлагаем подключить и что уже подключено.

Список — каталог парсера (`ingest.news.catalog.load_catalog`, `catalog.toml`): российские и зарубежные,
открытые и платные по API, с инструкцией подключения и переменной ключа. Без каталога (старая версия парсера)
— из его лент (`sources.toml`) с умолчаниями. Подключён — если парсер уже читает источник или пользователь
отметил его сам. Ключи API в прототипе не принимаем — только инструкция, куда ключ кладётся на сервере.
Открытую ленту пользователь может отключить: её новости уходят из его ленты, у остальных остаются.
«Для вашей отрасли» — у источника есть префикс ОКВЭД компании пользователя или её крупных контрагентов.
"""

import datetime as dt
import tomllib
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Protocol

from psycopg_pool import ConnectionPool

from api.contract import SourceEntry

if TYPE_CHECKING:
    from api.ranking import NewsEvent
    from api.records import CompanyRecord, Flow

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
                "about": getattr(s, "about", None),
                "benefit": getattr(s, "benefit", None),
                "access": getattr(s, "access", None),
                "full_text": getattr(s, "full_text", None),
                "industries": list(getattr(s, "industries", None) or []),
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
            "about": None,
            "benefit": None,
            "access": "Бесплатно, уже в вашей ленте" if kind == "free" else None,
            "industries": [],
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
        self._state: dict[tuple[str, str], str] = {}

    def connected(self, persona_id: str) -> set[str]:
        return {s for (p, s), state in self._state.items() if p == persona_id and state == "on"}

    def disconnected(self, persona_id: str) -> set[str]:
        return {s for (p, s), state in self._state.items() if p == persona_id and state == "off"}

    def connect(self, persona_id: str, source_id: str) -> None:
        self._state[(persona_id, source_id)] = "on"

    def disconnect(self, persona_id: str, source_id: str) -> None:
        self._state[(persona_id, source_id)] = "off"


class PgConnections:
    """Отметки «подключён» — таблица source_connections (api.db)."""

    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def _ids(self, persona_id: str, state: str) -> set[str]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT source_id FROM source_connections WHERE persona_id = %s AND state = %s",
                (persona_id, state),
            ).fetchall()
        return {r[0] for r in rows}

    def connected(self, persona_id: str) -> set[str]:
        return self._ids(persona_id, "on")

    def disconnected(self, persona_id: str) -> set[str]:
        return self._ids(persona_id, "off")

    def _set(self, persona_id: str, source_id: str, state: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO source_connections (persona_id, source_id, state) VALUES (%s, %s, %s)"
                " ON CONFLICT (persona_id, source_id)"
                " DO UPDATE SET state = EXCLUDED.state, connected_at = now()",
                (persona_id, source_id, state),
            )

    def connect(self, persona_id: str, source_id: str) -> None:
        self._set(persona_id, source_id, "on")

    def disconnect(self, persona_id: str, source_id: str) -> None:
        self._set(persona_id, source_id, "off")


PUBLIC = (
    "id",
    "name",
    "country",
    "kind",
    "reliability",
    "topics",
    "about",
    "benefit",
    "access",
    "full_text",
    "how_to_connect",
    "docs_url",
    "icon_url",
    "note",
)


# контрагент — «ключевой», если на него приходится не меньше этой доли входящих или исходящих платежей
KEY_COUNTERPARTY_SHARE = 0.1


def company_industries(company: "CompanyRecord | None", flows: "list[Flow]") -> set[str]:
    """Коды ОКВЭД компании и её ключевых покупателей и поставщиков: поставщик общепита — оптовик (46.90),
    но его покупатели — рестораны (56), и источники об общепите — для его отрасли."""
    codes = {company.okved_code} if company is not None and company.okved_code else set()
    own = company.id if company is not None and hasattr(company, "id") else None
    for direction in ("in", "out"):
        side = [f for f in flows if f.direction == direction and f.counterparty_id != own]  # без самоплатежей
        total = sum(f.amount for f in side) or 1.0
        for f in side:
            if (
                f.counterparty is not None
                and f.counterparty.okved_code
                and f.amount / total >= KEY_COUNTERPARTY_SHARE
            ):
                codes.add(f.counterparty.okved_code)
    return codes


def for_industry(entry: dict, okveds: set[str]) -> bool:
    return any(code.startswith(prefix) for prefix in entry.get("industries") or [] for code in okveds)


def entry_state(entry: dict, mine: set[str], off: set[str]) -> tuple[bool, str | None]:
    """Подключён ли у пользователя и кем: сервис читает открытую ленту для всех, пока её не отключили."""
    if entry["id"] in off:
        return False, None
    if entry["connected"]:
        return True, "service"
    return (True, "user") if entry["id"] in mine else (False, None)


def catalog(connections: Connections, persona_id: str, okveds: set[str] | None = None) -> list[SourceEntry]:
    mine, off = connections.connected(persona_id), connections.disconnected(persona_id)
    okveds = okveds or set()
    out = []
    for e in catalog_entries():
        connected, by = entry_state(e, mine, off)
        out.append(
            SourceEntry(
                **{k: e.get(k) for k in PUBLIC},  # about, benefit, access — у старых записей их нет
                connected=connected,
                connected_by=by,
                can_disconnect=connected,
                for_your_industry=for_industry(e, okveds),
            )
        )
    # подключённые, затем полезные отрасли, российские, бесплатные
    out.sort(
        key=lambda s: (not s.connected, not s.for_your_industry, s.country != "ru", s.kind != "free", s.name)
    )
    return out


def disconnect_message(entry: dict) -> str:
    if entry["connected"]:
        return (
            f"Источник «{entry['name']}» отключён: его новости больше не попадут в вашу ленту."
            " Вернуть — кнопкой «Подключить»."
        )
    return f"Источник «{entry['name']}» отключён. Вернуть — кнопкой «Подключить»."


def publishers_of(source_ids: set[str]) -> set[str]:
    """Издатели лент отключённых источников — их новости уходят из ленты пользователя."""
    feeds = {e["id"]: e["feeds"] for e in catalog_entries()}
    names = {f["id"]: f.get("publisher") for f in _feeds()}
    return {names[f] for sid in source_ids for f in feeds.get(sid, []) if names.get(f)}


class WithoutPublishers:
    """Поставщик новостей без отключённых пользователем издателей: лента, брифинг и поиск отфильтрованы;
    одно событие по прямой ссылке (`event`) открывается — пользователь мог прийти к нему из закладки."""

    def __init__(self, news: Any, publishers: set[str]) -> None:
        self._news, self._publishers = news, publishers
        self.name = getattr(news, "name", "news")

    def _keep(self, events: "list[NewsEvent]") -> "list[NewsEvent]":
        return [e for e in events if e.publisher not in self._publishers]

    # отсеянные места добираем запасом: иначе без крупного издателя кандидатов в ленте стало бы заметно меньше
    RESERVE = 2

    def events(self, since: dt.datetime | None, limit: int) -> "list[NewsEvent]":
        return self._keep(self._news.events(since, limit * self.RESERVE))[:limit]

    def search(self, query: str, limit: int) -> "list[NewsEvent]":
        return self._keep(self._news.search(query, limit * self.RESERVE))[:limit]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._news, name)


def connect_message(entry: dict) -> str:
    """Что дальше после отметки «подключён»: открытый — уже в ленте; платный — куда положить ключ."""
    if entry["kind"] == "free":
        if entry["connected"]:
            return f"Источник «{entry['name']}» подключён: его новости снова приходят в вашу ленту."
        return "Источник отмечен подключённым; парсер начнёт читать его ленту после обновления стенда."
    where = f" — переменная {entry['key_env']} в файле .env на сервере" if entry.get("key_env") else ""
    last = entry["how_to_connect"][-1] if entry["how_to_connect"] else ""
    text = f"Источник отмечен подключённым. Чтобы новости пошли в ленту, нужен ключ API{where}."
    return f"{text} {last}".strip()
