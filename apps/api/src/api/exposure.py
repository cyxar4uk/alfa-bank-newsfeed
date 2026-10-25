"""Карта чувствительности: к чему уязвима компания и через что.

Правила — в каталоге `factors.toml`; здесь только виды сигналов и сборка карты. Функции чистые: на вход запись
компании, её платежи и компании группы, на выход `ExposureMap` — их же вызывает агент как инструмент.

Ссылки в доказательствах (`Evidence.ref`) — id признаков профиля (`feat:…`), фактор целиком — `exp:<code>`.
"""

import re
import string
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.contract import (
    ChannelKind,
    Evidence,
    ExposureChannel,
    ExposureLevel,
    ExposureMap,
    FactorExposure,
    LevelDefinition,
)
from api.profile import (
    Flows,
    aggregate_flows,
    countries,
    display_name,
    format_rub,
    format_share,
    payment_structure,
)
from api.records import COLUMN_OF, CompanyRecord, Flow

CATALOG_PATH = Path(__file__).with_name("factors.toml")

# подписи признаков в доказательствах
FIELD_LABELS = {
    "credit": "Кредиты в банке",
    "leasing": "Лизинг в банке",
    "deposit": "Депозиты в банке",
    "guarantee": "Гарантии в банке",
    "factoring": "Факторинг в банке",
    "salary_project": "Зарплатный проект в банке",
    "rko": "РКО в банке",
    "fts_flag": "ВЭД по данным ФТС",
}

# подстановки, которые можно использовать в текстах каталога
PLACEHOLDERS = {
    "activity",
    "sector",
    "share",
    "count",
    "total",  # всего других компаний группы — «кредиты у 11 из 28 других компаний группы»
    "countries",
    "direction",
    "region",
    "city",
    "coverage",
    "amount",
}

# признаки профиля, на которые ссылаются доказательства из платежей и группы
SIDE_FEATURES = {"customers": "feat:customer_sectors", "suppliers": "feat:supplier_sectors"}
GROUP_FEATURE = "feat:GROUP_ID"
INTRA_FEATURE = "feat:intra_group_share"

_OKVED_CLASS = re.compile(r"^\d{2}$")
_OKVED_PREFIX = re.compile(r"^\d{2}(\.\d+)*$")
Thresholds = list[tuple[float, float]]


# --- Каталог -------------------------------------------------------------------------------------


def _check_text(text: str) -> str:
    """Только именованные подстановки из PLACEHOLDERS, без форматов — иначе каталог не загрузится."""
    try:
        parts = list(string.Formatter().parse(text))
    except ValueError as error:
        raise ValueError(f"битый шаблон текста «{text}»: {error}") from error
    for _, name, spec, conversion in parts:
        if name is None:
            continue
        if name not in PLACEHOLDERS or spec or conversion:
            raise ValueError(
                f"в тексте «{text}» недопустимая подстановка {{{name}}};"
                f" можно: {', '.join(sorted(PLACEHOLDERS))}"
            )
    return text


def _check_thresholds(thresholds: Thresholds) -> Thresholds:
    for share, strength in thresholds:
        if not (0 <= share <= 1 and 0 <= strength <= 1):
            raise ValueError(f"пороги — доли и силы от 0 до 1, а не [{share}, {strength}]")
    return sorted(thresholds, key=lambda t: -t[0])


class SignalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "always",
        "flag",
        "own_okved",
        "workers",
        "fts",
        "region",
        "side_share",
        "group_okved",
        "group_flag",
        "group_suppliers_fts",
    ]
    text: str
    strength: float | None = Field(default=None, ge=0, le=1)
    thresholds: Thresholds = Field(default_factory=list, description="[[доля, сила], …]")
    channel: ChannelKind = "direct"
    estimate: bool = False
    field: str | None = None
    codes: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    only: list[str] = Field(default_factory=list)
    unless_only: list[str] = Field(default_factory=list)
    countries_unknown: bool = False
    with_okved: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    side: Literal["customers", "suppliers"] | None = None
    okved: list[str] = Field(default_factory=list)
    min_revenue_share: float | None = Field(default=None, gt=0, le=1)
    min_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "SignalConfig":
        _check_text(self.text)
        self.thresholds = _check_thresholds(self.thresholds)
        by_share = {"side_share", "group_suppliers_fts"}
        if self.kind in by_share and not self.thresholds:
            raise ValueError(f"сигналу {self.kind} нужны thresholds")
        if self.kind not in by_share and self.strength is None:
            raise ValueError(f"сигналу {self.kind} нужна strength")
        if self.kind in {"flag", "group_flag"} and self.field not in FIELD_LABELS:
            raise ValueError(f"неизвестное поле {self.field}; можно: {', '.join(FIELD_LABELS)}")
        if self.kind == "side_share":
            if self.side is None or not self.okved:
                raise ValueError("сигналу side_share нужны side и okved")
            if bad := [c for c in self.okved if not _OKVED_CLASS.match(c)]:
                raise ValueError(f"в side_share okved — двузначные классы ОКВЭД, а не {bad}")
        if self.kind in {"own_okved", "group_okved"} and not self.codes:
            raise ValueError(f"сигналу {self.kind} нужны codes")
        if bad := [c for c in [*self.codes, *self.with_okved] if not _OKVED_PREFIX.match(c)]:
            raise ValueError(f"коды ОКВЭД вида 46 или 46.71, а не {bad}")
        if self.kind == "group_okved" and self.min_revenue_share is None:
            raise ValueError("сигналу group_okved нужна min_revenue_share")
        if self.kind == "workers" and not self.values:
            raise ValueError("сигналу workers нужны values")
        if self.only and self.unless_only:
            raise ValueError("only и unless_only вместе не задаются")
        return self


class FactorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    signal: list[SignalConfig] = Field(min_length=1)


class DynamicConfig(BaseModel):
    """Факторы по классам ОКВЭД контрагентов: demand_56, supply_52…"""

    model_config = ConfigDict(extra="forbid")

    prefix: str = Field(pattern=r"^[a-z][a-z0-9]*$")
    side: Literal["customers", "suppliers"]
    label: str
    channel: ChannelKind
    min_share: float = Field(gt=0, le=1)
    thresholds: Thresholds = Field(min_length=1)
    text: str

    @model_validator(mode="after")
    def _check(self) -> "DynamicConfig":
        _check_text(self.text)
        self.thresholds = _check_thresholds(self.thresholds)
        return self


class Levels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: float = Field(default=0.6, gt=0, le=1)
    medium: float = Field(default=0.3, gt=0, le=1)
    # смысл уровней — показывается в API рядом с картой
    high_meaning: str = "сильная прямая связь"
    medium_meaning: str = "заметная связь"
    low_meaning: str = "слабая или косвенная связь"
    none_meaning: str = "сигналов в данных нет"
    no_data_meaning: str = "оценить нельзя: не хватает данных"

    def definitions(self) -> list[LevelDefinition]:
        return [
            LevelDefinition(level="high", min=self.high, max=None, meaning=self.high_meaning),
            LevelDefinition(level="medium", min=self.medium, max=self.high, meaning=self.medium_meaning),
            # сила округляется до сотых: низкая — от 0,01, ноль — «нет»
            LevelDefinition(level="low", min=0.01, max=self.medium, meaning=self.low_meaning),
            LevelDefinition(level="none", min=None, max=None, meaning=self.none_meaning),
            LevelDefinition(level="no_data", min=None, max=None, meaning=self.no_data_meaning),
        ]

    @model_validator(mode="after")
    def _order(self) -> "Levels":
        if self.medium >= self.high:
            raise ValueError("порог medium должен быть ниже high")
        return self


class PaymentRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_revenue_coverage: float = Field(default=0.05, ge=0, le=1)
    min_side_revenue_share: float = Field(default=0.01, ge=0, le=1)
    low_coverage: float = Field(default=0.3, ge=0, le=1)
    low_coverage_cap: float = Field(default=0.29, ge=0, le=1)
    # доля одного внешнего контрагента в стороне, с которой предупреждаем о концентрации
    concentration: float = Field(default=0.3, gt=0, le=1)


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    levels: Levels = Field(default_factory=Levels)
    payments: PaymentRules = Field(default_factory=PaymentRules)
    fx_direction: dict[str, Literal["импорт", "экспорт"]] = Field(default_factory=dict)
    dynamic: list[DynamicConfig] = Field(default_factory=list)
    factor: list[FactorConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> "Catalog":
        codes = [f.code for f in self.factor]
        if len(codes) != len(set(codes)):
            raise ValueError("коды факторов повторяются")
        prefixes = [d.prefix for d in self.dynamic]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("префиксы динамических факторов повторяются")
        if clash := [c for c in codes for p in prefixes if c == p or c.startswith(p + "_")]:
            raise ValueError(f"коды {clash} совпадают с динамическими факторами {prefixes}")
        if bad := [c for c in self.fx_direction if not _OKVED_PREFIX.match(c)]:
            raise ValueError(f"в fx_direction коды ОКВЭД вида 46 или 46.71, а не {bad}")
        return self

    def level(self, strength: float | None) -> ExposureLevel:
        if strength is None:
            return "no_data"
        if strength >= self.levels.high:
            return "high"
        if strength >= self.levels.medium:
            return "medium"
        return "low" if strength > 0 else "none"


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    with path.open("rb") as f:
        return Catalog.model_validate(tomllib.load(f))


@lru_cache
def default_catalog() -> Catalog:
    return load_catalog()


# --- Входные данные ------------------------------------------------------------------------------


@dataclass
class Context:
    company: CompanyRecord
    flows: Flows
    group: list[CompanyRecord]
    catalog: Catalog

    def __post_init__(self) -> None:
        self.structure = payment_structure(self.flows)
        self.countries = _country_set(self.company.fts_countries)

    def side(self, name: str):
        return getattr(self.structure, name) if self.structure else None

    def side_has_data(self, name: str) -> tuple[bool, str | None]:
        """Есть ли данные по стороне; если нет — почему."""
        rules = self.catalog.payments
        revenue = self.company.revenue
        if self.structure is None:
            return False, "нет платежей в выгрузке"
        coverage = self.structure.revenue_coverage
        if coverage is not None and coverage < rules.min_revenue_coverage:
            return False, f"платежи в выгрузке — {format_share(coverage)} выручки: цепочки не строим"
        side = self.side(name)
        what = "поступлений" if name == "customers" else "платежей поставщикам"
        if not side.amount:
            return False, f"внешних {what} в выгрузке нет"
        if revenue and side.amount < revenue * rules.min_side_revenue_share:
            return False, f"внешних {what} в выгрузке почти нет ({format_rub(side.amount)})"
        return True, None


@dataclass
class Hit:
    strength: float
    channel: ExposureChannel
    evidence: list[Evidence]
    estimate: bool
    note: str | None = None


def _country_set(raw: str | None) -> set[str]:
    return {c.strip().upper() for c in raw.split(",") if c.strip()} if raw else set()


def _matches(code: str | None, prefixes: list[str]) -> bool:
    """Код ОКВЭД входит в группировку: коды иерархичны — «46.2» включает 46.21…46.24, «46» — весь класс.

    Поэтому в каталоге — самый узкий нужный код (зерно — 46.21, а не 46.2: в 46.22 уже цветы).
    """
    return bool(code) and any(code.startswith(p) for p in prefixes)


def _by_thresholds(share: float, thresholds: Thresholds) -> float:
    return next((strength for minimum, strength in thresholds if share >= minimum), 0.0)


def _fmt(text: str, **values) -> str:
    # шаблоны проверены при загрузке каталога: только известные подстановки без форматов
    return text.format_map({name: values.get(name, "—") for name in PLACEHOLDERS})


def _activity(company: CompanyRecord) -> str:
    if not company.okved_code:
        return "нет кода"
    return f"{company.okved_code} {company.okved_name}" if company.okved_name else company.okved_code


def direction(company: CompanyRecord, catalog: Catalog) -> str | None:
    """Направление ВЭД по отрасли (самый длинный подходящий код); не определить — None."""
    code = company.okved_code or ""
    best = max((p for p in catalog.fx_direction if _matches(code, [p])), key=len, default=None)
    return catalog.fx_direction[best] if best else None


def _direction_text(company: CompanyRecord, catalog: Catalog) -> str:
    value = direction(company, catalog)
    return f"{value} (оценка по отрасли)" if value else "в данных не указано"


def _feat(column: str, label: str, value) -> Evidence:
    if isinstance(value, bool):
        value = "да" if value else "нет"
    return Evidence(ref=f"feat:{column}", label=label, value=str(value))


def _okved_evidence(company: CompanyRecord) -> Evidence:
    return _feat("MAINOKVED_CODE", "Основная деятельность", _activity(company))


def _apply_coverage_cap(ctx: Context, side_name: str, strength: float) -> tuple[float, str | None]:
    rules = ctx.catalog.payments
    side = ctx.side(side_name)
    if side.coverage < rules.low_coverage and strength > rules.low_coverage_cap:
        note = f"сила ограничена: отрасль известна лишь у {format_share(side.coverage)} суммы"
        return rules.low_coverage_cap, note
    return strength, None


def _side_words(side: str) -> tuple[str, str]:
    """(«поступлений» — для «доля …», подпись суммы стороны по классу ОКВЭД)."""
    if side == "customers":
        return "поступлений", "Внешние поступления от контрагентов с ОКВЭД"
    return "платежей", "Внешние платежи контрагентам с ОКВЭД"


# --- Виды сигналов -------------------------------------------------------------------------------


def _always(ctx: Context, s: SignalConfig) -> Hit | None:
    return Hit(
        s.strength,
        ExposureChannel(kind=s.channel, text=_fmt(s.text, activity=_activity(ctx.company))),
        [_okved_evidence(ctx.company)],
        s.estimate,
    )


def _flag(ctx: Context, s: SignalConfig) -> Hit | None:
    if not getattr(ctx.company, s.field):
        return None
    evidence = [_feat(COLUMN_OF[s.field], FIELD_LABELS[s.field], True)]
    return Hit(s.strength, ExposureChannel(kind=s.channel, text=_fmt(s.text)), evidence, s.estimate)


def _own_okved(ctx: Context, s: SignalConfig) -> Hit | None:
    if not _matches(ctx.company.okved_code, s.codes):
        return None
    text = _fmt(s.text, activity=_activity(ctx.company))
    return Hit(
        s.strength, ExposureChannel(kind=s.channel, text=text), [_okved_evidence(ctx.company)], s.estimate
    )


def _workers(ctx: Context, s: SignalConfig) -> Hit | None:
    if ctx.company.workers_fns not in s.values:
        return None
    evidence = [_feat("AMOUNT_WORKERS_FNS_GRADATION", "Сотрудники по данным ФНС", ctx.company.workers_fns)]
    return Hit(s.strength, ExposureChannel(kind=s.channel, text=_fmt(s.text)), evidence, s.estimate)


def _fts(ctx: Context, s: SignalConfig) -> Hit | None:
    company = ctx.company
    if not company.fts_flag:
        return None
    found = ctx.countries
    if s.countries_unknown and found:
        return None
    # условия по странам требуют, чтобы страны были известны
    if (s.only or s.unless_only) and not found:
        return None
    if s.only and not found <= {c.upper() for c in s.only}:
        return None
    if s.unless_only and found <= {c.upper() for c in s.unless_only}:
        return None
    if s.with_okved and not _matches(company.okved_code, s.with_okved):
        return None
    names = ", ".join(countries(company.fts_countries)) if company.fts_countries else "страны не указаны"
    uses_direction = ("{direction}" in s.text or bool(s.with_okved)) and direction(
        company, ctx.catalog
    ) is not None
    text = _fmt(s.text, countries=names, direction=_direction_text(company, ctx.catalog))
    evidence = [_feat("FTS_FLAG", "ВЭД по данным ФТС", True)]
    if company.fts_countries:
        evidence.append(_feat("FTS_COUNTRY_NAME", "Страны ВЭД", names))
    if uses_direction:
        evidence.append(_okved_evidence(company))
    return Hit(s.strength, ExposureChannel(kind=s.channel, text=text), evidence, s.estimate or uses_direction)


def _region(ctx: Context, s: SignalConfig) -> Hit | None:
    region = ctx.company.region
    if not region or (s.regions and region not in s.regions):
        return None
    evidence = [_feat("REGION", "Регион", region)]
    city = ctx.company.city
    if city:
        evidence.append(_feat("CITY", "Город", city))
    text = _fmt(s.text, region=region, city=city or region)
    return Hit(s.strength, ExposureChannel(kind=s.channel, text=text), evidence, s.estimate)


def _side_share(ctx: Context, s: SignalConfig) -> Hit | None:
    ok, _ = ctx.side_has_data(s.side)
    if not ok:
        return None
    side = ctx.side(s.side)
    matched = [x for x in side.sectors if x.okved in s.okved]
    share = sum(x.share for x in matched)
    strength = _by_thresholds(share, s.thresholds)
    if not strength:
        return None
    strength, note = _apply_coverage_cap(ctx, s.side, strength)
    what, _ = _side_words(s.side)
    parts = ", ".join(
        f"{x.sector or 'ОКВЭД ' + x.okved} ({x.okved}) — {format_share(x.share)}" for x in matched
    )
    ref = SIDE_FEATURES[s.side]
    evidence = [
        Evidence(
            ref=ref,
            label=f"Доля внешних {what} по классам ОКВЭД",
            value=f"{parts}; всего {format_share(share)} из {format_rub(side.amount)}",
        ),
        Evidence(
            ref=ref,
            label="Покрытие отраслей",
            value=f"отрасль известна у {format_share(side.coverage)} суммы",
        ),
    ]
    text = _fmt(s.text, share=format_share(share), coverage=format_share(side.coverage))
    return Hit(strength, ExposureChannel(kind=s.channel, text=text), evidence, s.estimate, note)


def _group_okved(ctx: Context, s: SignalConfig) -> Hit | None:
    members = [m for m in ctx.group if m.revenue]
    total = sum(m.revenue for m in members)
    matched = [m for m in members if _matches(m.okved_code, s.codes)]
    amount = sum(m.revenue for m in matched)
    if not total or not matched or amount / total < s.min_revenue_share:
        return None
    share = amount / total
    top = sorted(matched, key=lambda m: -m.revenue)[:3]
    evidence = [
        Evidence(
            ref=GROUP_FEATURE,
            label=f"Компании группы с ОКВЭД {', '.join(s.codes)}",
            value=f"{len(matched)} компаний, {format_rub(amount)} — {format_share(share)} выручки группы "
            "без самой компании; крупнейшие: "
            + ", ".join(f"{display_name(m, m.id).lower()} — {format_rub(m.revenue)}" for m in top),
        ),
    ]
    text = _fmt(s.text, share=format_share(share), count=len(matched), amount=format_rub(amount))
    return Hit(s.strength, ExposureChannel(kind=s.channel, text=text), evidence, s.estimate)


def _group_flag(ctx: Context, s: SignalConfig) -> Hit | None:
    matched = [m for m in ctx.group if getattr(m, s.field)]
    if len(matched) < s.min_count:
        return None
    evidence = [
        Evidence(
            ref=GROUP_FEATURE,
            label=f"{FIELD_LABELS[s.field]} у других компаний группы",
            value=f"{len(matched)} из {len(ctx.group)}",
        ),
    ]
    return Hit(
        s.strength,
        ExposureChannel(kind=s.channel, text=_fmt(s.text, count=len(matched), total=len(ctx.group))),
        evidence,
        s.estimate,
    )


def _group_suppliers_fts(ctx: Context, s: SignalConfig) -> Hit | None:
    pairs = ctx.flows.pairs.values()
    outgoing = sum(p.out_amount for p in pairs)
    importers = [
        p for p in pairs if p.out_amount and ctx.flows.in_group(p.counterparty) and p.counterparty.fts_flag
    ]
    if not outgoing or not importers:
        return None
    share = sum(p.out_amount for p in importers) / outgoing
    strength = _by_thresholds(share, s.thresholds)
    if not strength:
        return None
    names = sorted({c for p in importers for c in countries(p.counterparty.fts_countries or "")})
    top = sorted(importers, key=lambda p: -p.out_amount)[:3]
    evidence = [
        Evidence(
            ref=INTRA_FEATURE,
            label="Платежи компаниям своей группы с ВЭД",
            value=f"{format_share(share)} всех платежей компании; "
            + ", ".join(
                f"{display_name(p.counterparty, p.counterparty.id).lower()} — {format_rub(p.out_amount)}"
                f" ({p.counterparty.fts_countries or 'страны не указаны'})"
                for p in top
            ),
        ),
    ]
    text = _fmt(s.text, share=format_share(share), count=len(importers), countries=", ".join(names) or "—")
    return Hit(strength, ExposureChannel(kind=s.channel, text=text), evidence, s.estimate)


SIGNALS: dict[str, Callable[[Context, SignalConfig], Hit | None]] = {
    "always": _always,
    "flag": _flag,
    "own_okved": _own_okved,
    "workers": _workers,
    "fts": _fts,
    "region": _region,
    "side_share": _side_share,
    "group_okved": _group_okved,
    "group_flag": _group_flag,
    "group_suppliers_fts": _group_suppliers_fts,
}


# --- Сборка карты --------------------------------------------------------------------------------


def _factor(ctx: Context, factor: FactorConfig) -> FactorExposure:
    hits = [hit for s in factor.signal if (hit := SIGNALS[s.kind](ctx, s))]
    if not hits:
        return FactorExposure(
            id=f"exp:{factor.code}", code=factor.code, label=factor.label, strength=0.0, level="none"
        )
    hits.sort(key=lambda h: -h.strength)
    top = hits[0]
    evidence: list[Evidence] = []
    for hit in hits:
        evidence.extend(e for e in hit.evidence if e not in evidence)
    # канал — от самого сильного сигнала; остальные заметные каналы дописываем, чтобы было видно все пути
    others = [h.channel.text for h in hits[1:] if h.strength >= ctx.catalog.levels.medium]
    text = top.channel.text + ("; также " + "; ".join(others) if others else "")
    strength = round(top.strength, 2)
    return FactorExposure(
        id=f"exp:{factor.code}",
        code=factor.code,
        label=factor.label,
        strength=strength,
        level=ctx.catalog.level(strength),
        channel=ExposureChannel(kind=top.channel.kind, text=text),
        evidence=evidence,
        estimate=top.estimate,
        notes=[top.note] if top.note else [],
    )


def _dynamic(ctx: Context, rule: DynamicConfig) -> list[FactorExposure]:
    ok, reason = ctx.side_has_data(rule.side)
    if not ok:
        return [
            FactorExposure(
                id=f"exp:{rule.prefix}",
                code=rule.prefix,
                label=rule.label,
                strength=None,
                level="no_data",
                notes=[reason] if reason else [],
            )
        ]
    side = ctx.side(rule.side)
    what, whom = _side_words(rule.side)
    ref = SIDE_FEATURES[rule.side]
    result = []
    for sector in side.sectors:
        if sector.share < rule.min_share:
            continue
        strength = _by_thresholds(sector.share, rule.thresholds)
        strength, note = _apply_coverage_cap(ctx, rule.side, strength)
        name = sector.sector or f"ОКВЭД {sector.okved}"
        text = _fmt(
            rule.text,
            sector=f"{name} ({sector.okved})",
            share=format_share(sector.share),
            count=sector.counterparties,
        )
        code = f"{rule.prefix}_{sector.okved}"
        result.append(
            FactorExposure(
                id=f"exp:{code}",
                code=code,
                label=f"{rule.label}: {name}",
                strength=round(strength, 2),
                level=ctx.catalog.level(strength),
                channel=ExposureChannel(kind=rule.channel, text=text),
                evidence=[
                    Evidence(
                        ref=ref,
                        label=f"{whom} {sector.okved}",
                        value=f"{format_rub(sector.amount)} — {format_share(sector.share)}"
                        f" из {format_rub(side.amount)}, {sector.counterparties} контрагентов",
                    ),
                    Evidence(
                        ref=ref,
                        label="Покрытие отраслей",
                        value=f"отрасль известна у {format_share(side.coverage)} суммы",
                    ),
                ],
                coverage=side.coverage,
                okved=sector.okved,
                notes=[note] if note else [],
            )
        )
    if not result:
        result.append(
            FactorExposure(
                id=f"exp:{rule.prefix}",
                code=rule.prefix,
                label=rule.label,
                strength=0.0,
                level="none",
                coverage=side.coverage,
                notes=[
                    f"ни один класс ОКВЭД не даёт {format_share(rule.min_share)} {what}; "
                    f"отрасль известна у {format_share(side.coverage)} суммы"
                ],
            )
        )
    return result


def _warnings(ctx: Context, factors: list[FactorExposure]) -> list[str]:
    company, catalog = ctx.company, ctx.catalog
    warnings = []
    fx = next((f for f in factors if f.code == "fx"), None)
    if fx and fx.level not in ("none", "no_data") and fx.estimate:
        value = direction(company, catalog)
        warnings.append(
            f"направления ВЭД в данных нет: «{value}» — оценка по отрасли"
            if value
            else "направления ВЭД в данных нет, по отрасли его не определить"
        )
    estimated = [
        f.label for f in factors if f.estimate and f.code != "fx" and f.level not in ("none", "no_data")
    ]
    if estimated:
        warnings.append("оценка по отрасли, а не данные: " + ", ".join(estimated))
    structure = ctx.structure
    if structure is None:
        warnings.append("платежей в выгрузке нет — спрос и поставки не оцениваем")
        return warnings
    if (
        structure.revenue_coverage is not None
        and structure.revenue_coverage < catalog.payments.min_revenue_coverage
    ):
        warnings.append(
            f"платежи по компании покрывают {format_share(structure.revenue_coverage)} выручки — "
            "цепочки через контрагентов не строим"
        )
    for name, attr, what, who in (
        ("customers", "in_amount", "поступлений", "покупатель"),
        ("suppliers", "out_amount", "платежей поставщикам", "поставщик"),
    ):
        if not ctx.side_has_data(name)[0]:
            continue
        side = ctx.side(name)
        if side.coverage < catalog.payments.low_coverage:
            warnings.append(f"отрасль известна лишь у {format_share(side.coverage)} внешних {what}")
        top = max(ctx.flows.external(), key=lambda p: getattr(p, attr), default=None)
        if top and side.amount and getattr(top, attr) / side.amount >= catalog.payments.concentration:
            where = "есть в данных банка" if top.counterparty else "вне данных банка"
            # роль и доля вместо номера: «ваш крупнейший покупатель — 46 % внешних поступлений»
            warnings.append(
                f"ваш крупнейший {who} — {format_share(getattr(top, attr) / side.amount)} внешних {what} "
                f"({where}): зависимость от одного контрагента"
            )
    return warnings


def build_exposure(
    company: CompanyRecord,
    flows: list[Flow],
    group: list[CompanyRecord] | None = None,
    catalog: Catalog | None = None,
) -> ExposureMap:
    """Карта чувствительности компании. `group` — другие компании её группы (без неё самой)."""
    catalog = catalog or default_catalog()
    ctx = Context(
        company, aggregate_flows(company, flows), [m for m in group or [] if m.id != company.id], catalog
    )
    factors = [_factor(ctx, f) for f in catalog.factor]
    for rule in catalog.dynamic:
        factors.extend(_dynamic(ctx, rule))
    order = {"high": 0, "medium": 1, "low": 2, "no_data": 3, "none": 4}
    factors.sort(key=lambda f: (order[f.level], -(f.strength or 0), f.code))
    return ExposureMap(
        company_id=company.id,
        factors=factors,
        warnings=_warnings(ctx, factors),
        levels=catalog.levels.definitions(),
        catalog_version=catalog.version,
    )
