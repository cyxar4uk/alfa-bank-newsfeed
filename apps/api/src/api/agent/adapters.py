"""Временные реализации протоколов агента — до мёржа модулей карты (#28), цепочки (#29) и поиска.

`ProfileCompanyData` берёт профиль из БД теми же функциями, что `/api/companies/{id}`, а карту, цепочку и
группу выводит из профиля по правилам `03_features.md` упрощённо. `JsonlLibrary` ищет по файлам парсера
(`data/raw/derived`) простым совпадением основ слов. Когда появятся настоящие функции, адаптеры заменяются в
`api.agent.service`, код агента не меняется.
"""

import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from api.agent.ports import (
    AnalyticsHit,
    Chain,
    ChainCounterparty,
    Channel,
    Event,
    Expectation,
    ExposureFactor,
    FactorTag,
    GroupImpact,
    GroupMember,
    ParseError,
    SectorTag,
)
from api.contract import CompanyProfile, Persona, Relevance, Source, SourceTags
from api.okved import okved_prefix, sector_for
from api.personas import personas_for
from api.profile import GROUP_MEMBERS_SHOWN, build_profile, display_name, format_share
from api.repo import CompanyRepo

CAPITAL_INTENSIVE = {"35", "41", "42", "43", "49", "50", "51", "52", "68"}
CONSUMER_CLASSES = {"45", "47", "56"}
GOV_CLASSES = {"41", "42", "71"}
COMMODITY_BY_CLASS = {
    "commodity_oil_gas": {"06", "09", "19"},
    "commodity_metals": {"07", "24", "25"},
    "commodity_agro": {"01", "10", "11"},
    "commodity_fertilizers": {"20"},
}
# оптовая и розничная торговля сырьём — по коду подкласса
COMMODITY_TRADE = {
    "commodity_oil_gas": ("46.71", "47.30"),
    "commodity_metals": ("46.72",),
    "commodity_agro": ("46.21", "46.2", "46.3"),
}
LABELS = {
    "rate": "стоимость заёмных денег",
    "deposit_yield": "доходность свободных денег",
    "fx": "курс валют",
    "ved_logistics": "санкции, платежи и логистика ВЭД",
    "consumer": "потребительский спрос",
    "labor": "рынок труда и зарплаты",
    "gov": "госрасходы и бюджет",
    "inflation": "инфляция издержек",
    "region": "события региона",
    "commodity_oil_gas": "нефть и газ",
    "commodity_metals": "металлы",
    "commodity_agro": "агросырьё",
    "commodity_fertilizers": "удобрения",
}


MIN_CHANNEL_SHARE = 0.05  # канал через контрагентов меньше 5 % своей стороны оборота — шум


def _own_class(profile: CompanyProfile) -> str | None:
    """Двузначный класс ОКВЭД компании: в признаке код идёт вместе с названием («45.31.1 Торговля…»)."""
    value = next((f.value for f in profile.features if f.id == "feat:MAINOKVED_CODE"), None)
    return okved_prefix(str(value).split(" ", 1)[0]) if value else None


def _level(strength: float) -> str:
    return "high" if strength >= 0.6 else "medium" if strength >= 0.3 else "low" if strength > 0 else "none"


class ProfileCompanyData:
    def __init__(self, repo: CompanyRepo) -> None:
        self.repo = repo
        self._profiles: dict[str, CompanyProfile] = {}

    def persona(self, persona_id: str) -> Persona | None:
        return next((p for p in personas_for(self.repo) if p.id == persona_id), None)

    def profile(self, company_id: str) -> CompanyProfile | None:
        if company_id in self._profiles:
            return self._profiles[company_id]
        company = self.repo.get_company(company_id)
        if company is None:
            return None
        size, members = 1, []
        if company.group_id:
            size, members = self.repo.group(company.group_id, exclude=company.id, limit=GROUP_MEMBERS_SHOWN)
        profile = build_profile(
            company,
            self.repo.flows(company.id),
            group_size=size,
            group_members=members,
            industry=self.repo.industry(company),
        )
        self._profiles[company_id] = profile
        return profile

    def exposure_map(self, company_id: str) -> list[ExposureFactor]:
        p = self.profile(company_id)
        if p is None:
            return []
        v = {f.id: f.value for f in p.features}
        own = _own_class(p)
        out: list[ExposureFactor] = []

        def add(code, strength, text, refs, coverage=None, label=None):
            out.append(
                ExposureFactor(
                    code=code,
                    label=label or LABELS.get(code, code),
                    level=_level(strength),
                    strength=round(strength, 2),
                    channel_text=text,
                    refs=[r for r in refs if r in v],
                    coverage=coverage,
                )
            )

        debt = [
            x
            for x in ("feat:CL_PRODUCT_LOA_MARK", "feat:CL_PRODUCT_LEA_MARK", "feat:FACTORING_MARK")
            if v.get(x)
        ]
        if debt or own in CAPITAL_INTENSIVE:
            strength = 0.7 if v.get("feat:CL_PRODUCT_LOA_MARK") else 0.5 if debt else 0.4
            text = (
                "через собственный кредит"
                if v.get("feat:CL_PRODUCT_LOA_MARK")
                else "через лизинг и финансирование"
            )
            if not debt:
                text = "капиталоёмкая отрасль"
            add("rate", strength, text, [*debt, "feat:MAINOKVED_CODE"])
        if v.get("feat:CL_PRODUCT_DEP_MARK"):
            add("deposit_yield", 0.5, "через депозит в банке", ["feat:CL_PRODUCT_DEP_MARK"])
        if v.get("feat:FTS_FLAG"):
            countries = v.get("feat:FTS_COUNTRY_NAME") or []
            text = (
                "ВЭД"
                + (f": {', '.join(countries[:5])}" if countries else "")
                + "; направление — оценка по отрасли"
            )
            add("fx", 0.6, text, ["feat:FTS_FLAG", "feat:FTS_COUNTRY_NAME"])
            add("ved_logistics", 0.4, text, ["feat:FTS_FLAG", "feat:FTS_COUNTRY_NAME"])
        if p.payments is None:
            out.append(
                ExposureFactor(
                    code="demand", label="спрос покупателей", level="no_data", channel_text="платежей нет"
                )
            )
        else:
            for side, prefix, word in (
                (p.payments.customers, "demand", "поступлений"),
                (p.payments.suppliers, "supply", "платежей поставщикам"),
            ):
                feat = "feat:customer_sectors" if prefix == "demand" else "feat:supplier_sectors"
                for s in side.sectors[:4]:
                    if s.share < 0.05:
                        continue
                    strength = min(1.0, s.share * 1.6)
                    add(
                        f"{prefix}_{s.okved}",
                        strength,
                        f"{s.sector or s.okved}: {format_share(s.share)} {word}",
                        [feat, "feat:payments_turnover"],
                        coverage=side.coverage,
                        label=("спрос покупателей" if prefix == "demand" else "поставщики")
                        + f" · {s.sector or s.okved}",
                    )
        if own in CONSUMER_CLASSES:
            add("consumer", 0.6, "своя отрасль ориентирована на потребителя", ["feat:MAINOKVED_CODE"])
        if v.get("feat:CL_PRODUCT_ZPP_MARK") or str(
            v.get("feat:AMOUNT_WORKERS_FNS_GRADATION") or ""
        ).startswith("Более"):
            add(
                "labor",
                0.4,
                "большой штат и зарплатный проект",
                ["feat:AMOUNT_WORKERS_FNS_GRADATION", "feat:CL_PRODUCT_ZPP_MARK"],
            )
        if own in GOV_CLASSES or v.get("feat:CL_PRODUCT_GAR_MARK"):
            add(
                "gov",
                0.5,
                "госзаказ: отрасль или банковские гарантии",
                ["feat:MAINOKVED_CODE", "feat:CL_PRODUCT_GAR_MARK"],
            )
        full = str(v.get("feat:MAINOKVED_CODE") or "").split(" ", 1)[0]
        for code, classes in COMMODITY_BY_CLASS.items():
            trade = COMMODITY_TRADE.get(code, ())
            if own in classes or any(full.startswith(t) for t in trade):
                add(
                    code,
                    0.6,
                    "своя отрасль" if own in classes else "торговля этим сырьём",
                    ["feat:MAINOKVED_CODE"],
                )
        if own and (own[0] in "123" or own in {"45", "46", "47"}):
            add(
                "inflation",
                0.3,
                "торговля или производство: издержки растут с инфляцией",
                ["feat:MAINOKVED_CODE"],
            )
        if v.get("feat:REGION"):
            add("region", 0.2, f"регион: {v.get('feat:REGION')}", ["feat:REGION"])
        return out

    def counterparty_chain(self, company_id: str, event: Source) -> Chain:
        p = self.profile(company_id)
        if p is None:
            return Chain(gaps=["нет данных о компании"])
        own = _own_class(p)
        codes = [c for c in event.tags.okved if c]
        chain = Chain()
        if own and own in codes:
            chain.channels.append(
                Channel(
                    kind="direct",
                    okved=own,
                    sector=sector_for(own),
                    text=f"своя отрасль — {sector_for(own)}",
                    refs=["feat:MAINOKVED_CODE"],
                )
            )
        if p.payments is None:
            chain.gaps.append("платежей компании в данных нет — цепочек через контрагентов нет")
            return chain
        for side, kind, word, feat, role in (
            (p.payments.customers, "buyers", "поступлений", "feat:customer_sectors", "customer"),
            (p.payments.suppliers, "suppliers", "платежей поставщикам", "feat:supplier_sectors", "supplier"),
        ):
            for s in side.sectors:
                if s.okved not in codes or s.share < MIN_CHANNEL_SHARE:
                    continue
                cps = [
                    ChainCounterparty(
                        id=c.id,
                        display_name=c.display_name,
                        sector=c.sector,
                        share=c.share,
                        intra_group=c.intra_group,
                    )
                    for c in p.counterparties
                    if c.okved
                    and okved_prefix(c.okved) == s.okved
                    and c.role in (role, "both")
                    and not c.intra_group
                ]
                chain.channels.append(
                    Channel(
                        kind=kind,
                        factor=f"{'demand' if kind == 'buyers' else 'supply'}_{s.okved}",
                        okved=s.okved,
                        sector=s.sector,
                        share=s.share,
                        coverage=side.coverage,
                        strength=round(min(1.0, s.share * 1.6), 2),
                        text=f"{s.sector or s.okved}: {format_share(s.share)} {word}, "
                        f"{s.counterparties} контрагентов; отрасль известна у {format_share(side.coverage)} "
                        "суммы",
                        refs=[feat, "feat:payments_turnover"],
                        counterparties=cps,
                    )
                )
        group_cps = [c for c in p.counterparties if c.intra_group]
        if group_cps:
            chain.channels.append(
                Channel(
                    kind="group",
                    share=p.payments.intra_group_share,
                    text=f"внутригрупповой оборот — {format_share(p.payments.intra_group_share)} платежей,"
                    " отдельно от внешних",
                    refs=["feat:intra_group_share"],
                    counterparties=[
                        ChainCounterparty(
                            id=c.id,
                            display_name=c.display_name,
                            sector=c.sector,
                            share=c.share,
                            intra_group=True,
                        )
                        for c in group_cps
                    ],
                )
            )
        if p.payments.revenue_coverage is not None and p.payments.revenue_coverage < 0.1:
            chain.gaps.append(
                f"платежи покрывают {format_share(p.payments.revenue_coverage)} выручки — картина неполная"
            )
        return chain

    def group_impact(self, company_id: str, event: Source) -> GroupImpact | None:
        p = self.profile(company_id)
        if p is None or p.group is None or p.group.size <= 1:
            return None
        codes = set(event.tags.okved)
        members = []
        credit = fts = 0
        countries: Counter[str] = Counter()
        paid = {c.id: c.share for c in p.counterparties if c.intra_group}
        for mid in p.group.members:
            m = self.repo.get_company(mid)
            if m is None:
                continue
            factors = []
            cls = okved_prefix(m.okved_code)
            if cls and cls in codes:
                factors.append("direct")
            if m.credit or m.leasing or cls in CAPITAL_INTENSIVE:
                factors.append("rate")
            credit += bool(m.credit)
            if m.fts_flag:
                factors.append("fx")
                fts += 1
                countries.update(c.strip().title() for c in (m.fts_countries or "").split(",") if c.strip())
            if m.guarantee or cls in GOV_CLASSES:
                factors.append("gov")
            if factors:
                name = display_name(m, m.id)
                if m.id in paid:
                    name += f" · {format_share(paid[m.id])} платёжного оборота компании"
                members.append(
                    GroupMember(
                        id=m.id,
                        display_name=name,
                        sector=sector_for(m.okved_code),
                        revenue=m.revenue,
                        factors=factors,
                    )
                )
        revenue = sum(m.revenue or 0 for m in members) or None
        shown = len(p.group.members)
        text = (
            f"в группе {p.group.size} компаний; среди {shown} крупнейших других: кредит в банке у "
            f"{credit}, ВЭД у {fts}"
        )
        if countries:
            text += f" (страны: {', '.join(c for c, _ in countries.most_common(5))})"
        return GroupImpact(
            group_id=p.group.id,
            size=p.group.size,
            members=members,
            revenue_total=revenue,
            text=text,
            refs=["feat:GROUP_ID"],
        )

    def relevance(self, persona: Persona, event: Source) -> Relevance | None:
        return None


# --- поиск по файлам парсера -------------------------------------------------------------------------

_WORD = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_STOP = {
    "и",
    "в",
    "на",
    "по",
    "с",
    "о",
    "к",
    "от",
    "до",
    "за",
    "не",
    "что",
    "как",
    "это",
    "для",
    "из",
    "при",
    "года",
    "году",
}
_DISCLAIMER = ("Несанкционированное копирование", "Контакты и дисклеймер")


def _stems(text: str) -> list[str]:
    return [w.lower()[:6] for w in _WORD.findall(text or "") if len(w) > 2 and w.lower() not in _STOP]


def _event_from(row: dict) -> Event:
    tags = row.get("tags") or {}
    source = Source(
        id=row["id"],
        kind=row.get("kind", "news"),
        title=row.get("title", ""),
        publisher=row.get("publisher"),
        url=row.get("url"),
        published_at=row.get("published_at"),
        page=row.get("page"),
        fragment=row.get("fragment"),
        tags=SourceTags(
            topics=tags.get("topics", []),
            sectors=tags.get("sectors", []),
            okved=tags.get("okved", []),
            event_type=tags.get("event_type"),
            regions=tags.get("regions", []),
        ),
    )
    return Event(
        source=source,
        factors=[
            FactorTag(code=f["code"], strength=f.get("strength", 1.0), evidence=f.get("evidence", []))
            for f in tags.get("factors", [])
        ],
        sectors=[
            SectorTag(
                okved=s["okved"],
                name=s.get("name", ""),
                strength=s.get("strength", 1.0),
                via=s.get("via", "text"),
            )
            for s in tags.get("sector_links", [])
        ],
        expectations=[
            Expectation(
                who=e.get("who", ""),
                indicator=e.get("indicator"),
                values=e.get("values", []),
                quote=e["quote"],
            )
            for e in row.get("expectations", [])
            if e.get("quote")
        ],
    )


class JsonlLibrary:
    def __init__(self, derived: Path, snapshot: Path | None = None) -> None:
        news_file = derived / "news.jsonl"
        if not news_file.exists() and snapshot is not None:
            news_file = snapshot
        self.news = {e.id: e for e in (_event_from(r) for r in _read(news_file))}
        self.pages = {r["id"]: r for r in _read(derived / "alfa_pages.jsonl")}
        self.fragments = [
            r
            for r in _read(derived / "alfa_fragments.jsonl")
            if not any(d in r["fragment"] for d in _DISCLAIMER)
        ]
        docs = [_stems(f"{r['title']} {r['fragment']}") for r in self.fragments]
        self._df = Counter(s for d in docs for s in set(d))
        self._docs = [Counter(d) for d in docs]
        self._user: dict[str, Event] = {}

    def get_event(self, event_id: str) -> Event | None:
        return self.news.get(event_id) or self._user.get(event_id)

    def search_news(self, query, *, factors=None, before=None, limit=5):
        q = set(_stems(query))
        scored = []
        for e in self.news.values():
            if before and e.source.published_at and e.source.published_at >= before:
                continue
            words = set(_stems(f"{e.source.title} {e.source.fragment}"))
            score = len(q & words) + 0.5 * len({f.code for f in e.factors} & set(factors or []))
            if score >= 2:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]

    def search_alfa_analytics(self, query, *, factors=None, limit=5, material=None):
        q = _stems(query)
        n = len(self._docs)
        scored = []
        for row, doc in zip(self.fragments, self._docs, strict=True):
            if row.get("stale") or (material and not row["id"].startswith(material + "#")):
                continue
            score = sum(math.log(1 + n / (1 + self._df[s])) for s in set(q) if s in doc)
            codes = {f["code"] for f in (row.get("tags") or {}).get("factors", [])}
            score += 1.5 * len(codes & set(factors or []))
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, row in scored[:limit]:
            published = row.get("published_at")
            out.append(
                AnalyticsHit(
                    source=Source(
                        id=row["id"],
                        kind="alfa_analytics",
                        title=row["title"],
                        publisher="Альфа-Банк",
                        published_at=published,
                        page=row.get("page"),
                        fragment=row["fragment"],
                    ),
                    page_ref=row["page_ref"],
                    material_date=dt.datetime.fromisoformat(published).date() if published else None,
                    stale=bool(row.get("stale")),
                )
            )
        return out

    def alfa_page_text(self, ref: str) -> str | None:
        page_ref = re.sub(r"(#p\d+)-\d+$", r"\1", ref)
        page = self.pages.get(page_ref)
        if page is None:
            return None
        # цитата могла прийти из любого движка распознавания — сверяем с обоими текстами страницы
        return "\n".join(t for t in (page.get("fragment"), page.get("vlm_text")) if t)

    def parse_news(self, *, text=None, url=None):
        if url and not text:
            raise ParseError("разбор по ссылке пока недоступен — вставьте текст новости")
        text = (text or "").strip()
        if len(text) < 40:
            raise ParseError("слишком короткий текст: нужна новость хотя бы в одно-два предложения")
        title = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:200]
        sid = "src:news:user-" + hashlib.sha256(text.encode()).hexdigest()[:12]
        stems = set(_stems(text))
        rules = {
            "rate": {"ставк", "ключев", "кредит"},
            "deposit_yield": {"депози", "доходн"},
            "fx": {"курс", "рубль", "рубля", "доллар", "юань"},
            "inflation": {"инфляц", "дефляц", "цены"},
            "consumer": {"потреб", "рознич", "продаж"},
            "labor": {"зарпла", "безраб", "вакан"},
            "gov": {"бюджет", "госзак"},
        }
        factors = [
            FactorTag(code=c, strength=0.8)
            for c, keys in rules.items()
            if any(s.startswith(k) for s in stems for k in keys)
        ]
        sectors = [
            SectorTag(okved=code, name=sector_for(code) or code, strength=0.8)
            for code, keys in SECTOR_RULES.items()
            if any(s.startswith(k) for s in stems for k in keys)
        ]
        event = Event(
            source=Source(
                id=sid,
                kind="news",
                title=title,
                publisher="текст пользователя",
                fragment=text[:500],
                tags=SourceTags(okved=[t.okved for t in sectors]),
            ),
            factors=factors,
            sectors=sectors,
            body=text,
        )
        self._user[sid] = event
        return event


# отрасли своей новости по основам слов — временно, пока разбор не делает модуль поиска
SECTOR_RULES = {
    "01": {"урожа", "зерно", "зерна", "пшениц", "сельхоз"},
    "19": {"нефтеп", "бензин", "дизел", "топлив"},
    "41": {"строит", "застро", "девелоп"},
    "45": {"автомо", "автокр", "автоса"},
    "46": {"оптов"},
    "47": {"рознич", "ритейл", "магази"},
    "49": {"перево", "грузоп", "логист"},
    "56": {"рестор", "общепи", "кафе"},
}


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
