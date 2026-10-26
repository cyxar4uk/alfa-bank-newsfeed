"""Метрики замера по сырым ответам (results/latest.json) и таблица для docs/quality.md и README.

Всё здесь детерминированно: модели не вызываются, повторный расчёт по тем же ответам даёт ту же таблицу.
"""

import bisect
import json
import re
import statistics
from pathlib import Path

MINOR = 0.3
TABLE_START, TABLE_END = "<!-- eval:table:start -->", "<!-- eval:table:end -->"
DETAILS_START, DETAILS_END = "<!-- eval:details:start -->", "<!-- eval:details:end -->"
SOURCED = {"fact", "bank", "data", "quote"}
LEVEL_RU = {"act": "важно", "watch": "следить", "info": "к сведению", None: "—"}

# --- числа ----------------------------------------------------------------------------------------------

MONTHS = r"(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*"
STRIP = [
    re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b"),  # 11.09.2026
    re.compile(r"\b\d{1,2}\s*[–-]\s*\d{1,2}\s+" + MONTHS, re.IGNORECASE),  # 25–31 августа
    re.compile(r"\b\d{1,2}(?:-го)?\s+" + MONTHS, re.IGNORECASE),  # 23 октября
    re.compile(r"\b\d{1,2}:\d{2}\b"),  # 12:13
    re.compile(r"\b(?:19[89]\d|20[0-3]\d)\b"),  # годы
    re.compile(r"\b\d[КкПпМмQqHh]\d{2}\b"),  # 4К26, 1П26, 7М26
    re.compile(r"\bU_\d+\b"),
    re.compile(r"\b[A-Za-z]+[-_]\d[\w-]*"),  # коды материалов: macro-1h26, keyrate-2026-09
]
NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?(?![\w])")


def numbers(text: str) -> list[tuple[float, int, str]]:
    """Значимые числа текста: (значение, знаков после запятой, как написано). Даты, годы, коды и целые до 10
    не считаются — это счёт («два фактора»), а не данные."""
    for pattern in STRIP:
        text = pattern.sub(" ", text)
    out = []
    for m in NUMBER.finditer(text):
        whole = re.sub(r"[   ]", "", m.group(1))
        frac = m.group(2) or ""
        value = float(f"{whole}.{frac}" if frac else whole)
        if not frac and value <= 10:
            continue
        out.append((value, len(frac), m.group(0)))
    return out


def walk(obj, strings: list[str], values: list[float]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            walk(v, strings, values)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, strings, values)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, int | float):
        values.append(float(obj))
    elif isinstance(obj, str):
        strings.append(obj)


class Pool:
    """Числа, которые есть в данных: из текстов как написаны, из чисел JSON — в масштабах ₽, тыс., млн, млрд,
    трлн и долях в процентах."""

    def __init__(self, *objs) -> None:
        strings: list[str] = []
        raw: list[float] = []
        for obj in objs:
            walk(obj, strings, raw)
        found = [v for s in strings for v, _, _ in numbers(s)]
        for v in raw:
            found += [v, v / 1e3, v / 1e6, v / 1e9, v / 1e12]
            if abs(v) <= 1.5:
                found.append(v * 100)
        self.values = sorted({round(abs(v), 6) for v in found})
        self.text = " ".join(strings).lower()

    def has(self, value: float, decimals: int) -> bool:
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        i = bisect.bisect_left(self.values, value - tol)
        return i < len(self.values) and self.values[i] <= value + tol


# --- утверждения карточки -------------------------------------------------------------------------------


def statements(insight: dict) -> list[dict]:
    out = []
    for block in ("what_happened", "why_it_matters", "bank_view"):
        for s in insight.get(block) or []:
            out.append(
                {"block": block, "origin": s["origin"], "text": s["text"], "refs": s.get("refs") or []}
            )
    for block in ("risks", "opportunities", "factors"):
        for s in (insight.get("consequences") or {}).get(block) or []:
            out.append(
                {"block": block, "origin": s["origin"], "text": s["text"], "refs": s.get("refs") or []}
            )
    verdict = insight.get("verdict") or {}
    for key in ("headline", "why"):
        if verdict.get(key):
            out.append(
                {
                    "block": f"verdict.{key}",
                    "origin": "verdict",
                    "text": verdict[key],
                    "refs": verdict.get("refs") or [],
                }
            )
    for step in verdict.get("steps") or []:
        out.append({"block": "verdict.steps", "origin": "action", "text": step["text"], "refs": []})
    for a in insight.get("actions") or []:
        out.append({"block": "actions", "origin": "action", "text": a["text"], "refs": a.get("refs") or []})
    bp = insight.get("bank_position") or {}
    if bp.get("found") and bp.get("statement"):
        out.append(
            {
                "block": "bank_position",
                "origin": "bank",
                "text": bp["statement"],
                "refs": [bp["source_id"]] if bp.get("source_id") else [],
            }
        )
    for q in insight.get("quotes") or []:
        out.append({"block": "quotes", "origin": "quote", "text": q["text"], "refs": [q["source_id"]]})
    return out


def data_part(pool: dict) -> list:
    return [pool.get(k) for k in ("profile", "exposure", "group_impact", "chain", "feed_item", "risk_map")]


def ref_material(ref: str, pool: dict, item: dict) -> list | None:
    """Чем подтверждается ссылка; None — ссылка ни на что не указывает.

    feat:… — только свой признак профиля (его подпись и значение), exp:… — свой фактор карты,
    src:… — материал целиком. Всё остальное (group, chain, payments) без точной проверки не засчитывается.
    """
    if ref.startswith("src:"):
        src = (pool.get("sources") or {}).get(ref)
        if src is None:
            return None
        extra = []
        event = pool.get("event") or {}
        if ref == event.get("id"):
            extra.append(event.get("text"))
        if ref.startswith("src:news:user-"):
            extra.append(item.get("text"))
        return [src.get("title"), src.get("fragment"), src.get("text"), *extra]
    if ref.startswith("feat:"):
        for f in (pool.get("profile") or {}).get("features") or []:
            if f["id"] == ref:
                return [f.get("label"), f.get("display"), f.get("value")]
        return None
    if ref.startswith("exp:"):
        for f in (pool.get("exposure") or {}).get("factors") or []:
            if f["id"] == ref:
                return [f.get("label"), f.get("strength"), *[e.get("value") for e in f.get("evidence") or []]]
        return None
    return None


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[«»\"“”„]", "", text or "")).strip().lower()


def check_statement(s: dict, pool: dict, item: dict) -> dict:
    materials, missing = [], []
    for ref in s["refs"]:
        m = ref_material(ref, pool, item)
        if m is None:
            missing.append(ref)
        else:
            materials.append(m)
    ref_pool = Pool(materials)
    unfounded = [raw for v, d, raw in numbers(s["text"]) if not ref_pool.has(v, d)]
    quote_ok = True
    if s["origin"] == "quote":
        quote_ok = any(norm(s["text"]) in norm(" ".join(x or "" for x in m)) for m in materials)
    ok = bool(s["refs"]) and not missing and not unfounded and quote_ok
    return {
        "ok": ok,
        "no_refs": not s["refs"],
        "missing_refs": missing,
        "unfounded": unfounded,
        "quote_ok": quote_ok,
    }


NAME = re.compile(
    r"(?<![.!?:]\s)(?<!^)(?<![«\"])\b([A-ZА-ЯЁ][a-zа-яё]+(?:[- ][A-ZА-ЯЁ][a-zа-яё]+)*|[A-Z]{2,})"
)
COMMON = {
    "альфа-банк",
    "альфа",
    "банк",
    "банка",
    "россии",
    "россия",
    "рф",
    "цб",
    "минфин",
    "росстат",
    "фнс",
    "фтс",
    "мосбиржа",
    "мосбирже",
    "вэд",
    "ндс",
    "ип",
    "ооо",
    "оао",
    "рко",
    "ofz",
    "офз",
    "ввп",
    "ес",
    "сша",
    "usd",
    "eur",
    "cny",
    "brent",
    "urals",
    "forex",
    "минэк",
    "госдума",
    "правительство",
}


def names(text: str) -> list[str]:
    return [m.group(1) for m in NAME.finditer(text) if m.group(1).lower() not in COMMON]


def name_in_pool(name: str, pool: Pool) -> bool:
    words = [w for w in re.split(r"[- ]", name.lower()) if w]
    return all((w[:-2] if len(w) > 4 else w) in pool.text for w in words)


def score_build(item: dict) -> dict:
    insight, pool = item["insight"], item.get("pool") or {}
    whole = Pool(list(pool.values()), item.get("text"), insight.get("sources"))
    rows = []
    for s in statements(insight):
        row = {**s}
        if s["origin"] in SOURCED or s["block"] == "bank_position":
            row["check"] = check_statement(s, pool, item)
        if s["origin"] != "estimate":
            row["fabricated_numbers"] = [raw for v, d, raw in numbers(s["text"]) if not whole.has(v, d)]
            row["unknown_names"] = [n for n in names(s["text"]) if not name_in_pool(n, whole)]
        rows.append(row)
    return {"statements": rows}


# --- метрики ---------------------------------------------------------------------------------------------


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f} %" if b else "—"


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def selection_metrics(results: dict, cases: dict) -> dict:
    tp = fp = tn = fn = 0
    in_feed_tp = in_feed_fp = 0
    per = {}
    errors = []
    titles = {n["id"]: n["title"] for n in results["news"]}
    for pid, rows in results["selection"].items():
        p = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        for eid, r in rows.items():
            if not r.get("judge"):
                continue
            system = (r["system_score"] or 0) >= MINOR
            truth = r["judge"]["touches"]
            key = ("tp" if truth else "fp") if system else ("fn" if truth else "tn")
            p[key] += 1
            if r["system_score"] is not None:
                if truth:
                    in_feed_tp += 1
                else:
                    in_feed_fp += 1
            if key in ("fp", "fn"):
                errors.append(
                    {
                        "persona": pid,
                        "event_id": eid,
                        "title": titles.get(eid, ""),
                        "kind": key,
                        "score": r["system_score"],
                        "why": r["judge"].get("why", ""),
                    }
                )
        per[pid] = p
        tp, fp, tn, fn = tp + p["tp"], fp + p["fp"], tn + p["tn"], fn + p["fn"]
    manual = cases.get("manual_check") or []
    agree = sum(1 for m in manual if m.get("judge") is not None and m["judge"] == m["label"])
    system_ok = sum(1 for m in manual if m.get("system") is not None and m["system"] == m["label"])
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "per": per,
        "errors": errors,
        "manual": len(manual),
        "manual_agree": agree,
        "manual_system_ok": system_ok,
        "in_feed_tp": in_feed_tp,
        "in_feed_fp": in_feed_fp,
    }


def coverage_check(item: dict) -> dict | None:
    """Лента и карточка об одном событии: уровень и числа охвата группы."""
    pool = item.get("pool") or {}
    feed_item = pool.get("feed_item")
    if item["kind"] != "feed" or not feed_item:
        return None
    insight = item["insight"]
    feed_level = (feed_item.get("takeaway") or {}).get("level")
    card_level = (insight.get("verdict") or {}).get("level")
    gi = feed_item.get("group_impact") or {}
    profile = pool.get("profile") or {}
    allowed = {
        gi.get(k)
        for k in ("affected_count", "affected_with_credit", "major_count", "companies_total", "others_total")
    }
    allowed.add((profile.get("group") or {}).get("size"))
    exposure_text = json.dumps(pool.get("exposure") or {}, ensure_ascii=False)
    allowed |= {int(v) for v, d, _ in numbers(exposure_text) if not d}
    allowed.discard(None)
    pattern = re.compile(r"(\d+)\s+(?:из\s+(\d+)\s+)?(?:других\s+|крупных\s+|дочерних\s+)?компани", re.I)
    card = " ".join(s["text"] for s in statements(insight))
    feed_text = " ".join(
        filter(None, [(feed_item.get("takeaway") or {}).get("text"), feed_item.get("short"), gi.get("text")])
    )
    bad = []
    for where, text in (("карточка", card), ("лента", feed_text)):
        for m in pattern.finditer(text):
            for g in m.groups():
                if g and int(g) > 10 and int(g) not in allowed:
                    bad.append(f"{where}: «{m.group(0)}»")
    feed_numbers = [(v, d, raw) for v, d, raw in numbers(feed_text)]
    card_pool = Pool([card])
    lost = [raw for v, d, raw in feed_numbers if not card_pool.has(v, d)]
    compared = bool(pattern.search(card))
    return {
        "event_id": item["event_id"],
        "persona": item["persona"],
        "title": insight["event"]["title"],
        "feed_level": feed_level,
        "card_level": card_level,
        "level_ok": feed_level == card_level,
        "compared": compared,
        "counts_ok": not bad or not compared,
        "bad": bad,
        "feed_numbers": [r for _, _, r in feed_numbers],
        "feed_numbers_in_card": not lost,
        "lost": lost,
        "feed_text": feed_text,
    }


def report(results: dict, cases: dict, root: Path) -> None:
    builds = [b for b in results["builds"] if b.get("insight")]
    scored = [(b, score_build(b)) for b in builds]
    sel = selection_metrics(results, cases)

    sourced = [(b, s) for b, sc in scored for s in sc["statements"] if "check" in s]
    sourced_ok = sum(1 for _, s in sourced if s["check"]["ok"])
    no_refs = sum(1 for _, s in sourced if s["check"]["no_refs"])
    bad_refs = sum(1 for _, s in sourced if s["check"]["missing_refs"])
    bad_nums = sum(1 for _, s in sourced if s["check"]["unfounded"])
    bad_quotes = sum(1 for _, s in sourced if not s["check"]["quote_ok"])

    cov = [c for b in builds if (c := coverage_check(b))]
    level_ok = sum(c["level_ok"] for c in cov)
    counts_ok = sum(c["counts_ok"] for c in cov if c["compared"])
    compared_n = sum(c["compared"] for c in cov)
    lost_ok = sum(c["feed_numbers_in_card"] for c in cov if c["feed_numbers"])
    lost_n = sum(1 for c in cov if c["feed_numbers"])

    bank_items = [
        (b, s) for b in builds if (b.get("bank_judge") or {}).get("found") for s in b["bank_judge"]["items"]
    ]
    on_topic = sum(1 for _, s in bank_items if s["on_topic"])
    no_bank = [b for b in builds if b.get("bank_judge") and not b["bank_judge"]["found"]]
    no_bank_ok = sum(1 for b in no_bank if not b["bank_judge"]["exists"])
    cards_off = sum(
        1
        for b in builds
        if (b.get("bank_judge") or {}).get("found")
        and not all(s["on_topic"] for s in b["bank_judge"]["items"])
    )
    cards_found = sum(1 for b in builds if (b.get("bank_judge") or {}).get("found"))

    checked = [(b, s) for b, sc in scored for s in sc["statements"] if "fabricated_numbers" in s]
    with_numbers = [(b, s) for b, s in checked if numbers(s["text"])]
    fab = [(b, s) for b, s in checked if s["fabricated_numbers"]]
    fab_numbers = sum(len(s["fabricated_numbers"]) for _, s in fab)
    all_numbers = sum(len([1 for _ in numbers(s["text"])]) for _, s in checked)
    fab_cards = len({id(b) for b, _ in fab})
    unknown = [(b, s) for b, s in checked if s["unknown_names"]]

    fresh = [b for b in builds if b["seconds"] > 3]
    secs = [b["seconds"] for b in fresh]
    costs = [b["cost_rub"] for b in fresh if b.get("cost_rub")]
    journal = [j for j in results.get("journal") or [] if not j.get("cached") and j.get("ok")]

    unseen = [b for b in results["builds"] if b["kind"] == "unseen"]
    unseen_ok = sum(1 for b in unseen if b.get("status") == 200)
    refs = [b for b in builds if b["kind"] == "reference" and b.get("checklist")]
    ref_ok = sum(1 for b in refs for c in b["checklist"] if c["ok"])
    ref_all = sum(len(b["checklist"]) for b in refs)

    def money(v):
        return "—" if v is None else f"{v:.2f} ₽".replace(".", ",")

    def sec(v):
        return "—" if v is None else f"{v:.0f} с"

    p_touch = pct(sel["tp"], sel["tp"] + sel["fp"])
    p_skip = pct(sel["tn"], sel["tn"] + sel["fn"])
    table = [
        "| Что меряем | Результат | Как считали |",
        "|---|---|---|",
        f"| Отбор: точность «касается» | **{p_touch}** ({sel['tp']} из {sel['tp'] + sel['fp']}) | события с "
        f"оценкой ≥ 0,3 в ленте, судья согласен, что касаются; полнота — {pct(sel['tp'], sel['tp'] + sel['fn'])} |",
        f"| Отбор: точность «не касается» | **{p_skip}** ({sel['tn']} из {sel['tn'] + sel['fn']}) | события "
        f"ниже 0,3 или не в ленте, судья согласен, что не касаются |",
        f"| Судья vs ручная проверка | **{sel['manual_agree']} из {sel['manual']}** | выборка разметки, "
        f"проверенная вручную: метки по заголовку и карточке, судья — отдельно |",
        f"| Опора на источники | **{pct(sourced_ok, len(sourced))}** ({sourced_ok} из {len(sourced)}) | "
        f"утверждения «факт», «банк», «данные» и цитаты: ссылка находится (признак, фактор карты или источник), числа есть в ней; группа, цепочка и платежи по ссылке не засчитываются |",
        f"| Числа охвата: лента = карточка | **{pct(counts_ok, compared_n)}** ({counts_ok} из {compared_n}) | "
        f"счёт компаний группы в ленте и карточке сходится с расчётом охвата; уровень совпал в "
        f"{level_ok} из {len(cov)}, числа вывода ленты есть в карточке в {lost_ok} из {lost_n} |",
        f"| Позиция банка по теме | **{pct(on_topic, len(bank_items))}** ({on_topic} из {len(bank_items)}) | "
        f"утверждения банка о том же факторе, что событие; карточек с цитатой не по теме — {cards_off} из "
        f"{cards_found} |",
        f"| «Позиции банка нет» — верно | **{pct(no_bank_ok, len(no_bank))}** ({no_bank_ok} из {len(no_bank)}) | "
        f"судья не нашёл в материалах банка позиции по теме |",
        f"| Выдумки: числа | **{fab_numbers} из {all_numbers}** чисел, в {fab_cards} из {len(builds)} карточек | "
        f"числа выводов, которых нет ни в данных компании, ни в источниках (кроме расчётов «оценка») |",
        f"| Выдумки: имена | **{sum(len(s['unknown_names']) for _, s in unknown)}** | названия и имена, "
        f"которых нет в данных (кандидаты; вручную не разобраны, метрика шумная) |",
        f"| Время разбора | **медиана {sec(quantile(secs, 0.5))}, p90 {sec(quantile(secs, 0.9))}** | {len(secs)} "
        f"новых сборок, от запроса до готовой карточки |",
        f"| Стоимость разбора | **медиана {money(quantile(costs, 0.5))}, p90 {money(quantile(costs, 0.9))}** | "
        f"по трассе (журналу вызовов моделей) каждой сборки |",
        f"| Новые новости | **{unseen_ok} из {len(unseen)}** разобраны | своя новость, которой нет в базе: "
        f"отрасль клиента, не по теме, английский, инструкция в тексте, шум |",
        f"| Эталоны | **{ref_ok} из {ref_all}** пунктов чек-листа | {len(refs)} эталонов, судья по чек-листу |",
    ]
    stamp = (
        f"Прогон {results['started_at'][:16].replace('T', ' ')} МСК: {len(results['selection'])} "
        f"пользователей, {len(results['news'])} новостей из базы, {len(builds)} карточек; расход — "
        f"{money(results['build_spent_rub'])} на разборы и {money(results['judge']['spent_rub'])} на судью."
    )
    table_md = "\n".join([stamp, "", *table])

    details = [
        details_selection(sel),
        details_sources(sourced, sourced_ok, no_refs, bad_refs, bad_nums, bad_quotes),
        details_coverage(cov),
        details_bank(bank_items, no_bank),
        details_fab(fab, unknown, with_numbers),
        details_time(fresh, journal),
        details_unseen(unseen, scored),
        details_refs(refs),
    ]
    for path in (root / "docs" / "quality.md", root / "README.md"):
        replace_block(path, TABLE_START, TABLE_END, table_md)
    replace_block(root / "docs" / "quality.md", DETAILS_START, DETAILS_END, "\n\n".join(details))
    print(table_md)


def replace_block(path: Path, start: str, end: str, body: str) -> None:
    if not path.exists():
        print(f"нет {path} — блок не вписан")
        return
    text = path.read_text(encoding="utf-8")
    if start not in text or end not in text:
        print(f"в {path.name} нет меток {start} … {end} — блок не вписан")
        return
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    path.write_text(f"{head}{start}\n{body}\n{end}{tail}", encoding="utf-8")


def cut(text: str, n: int = 140) -> str:
    text = re.sub(r"\s+", " ", text or "").replace("|", "/")
    return text if len(text) <= n else text[: n - 1] + "…"


def details_selection(sel: dict) -> str:
    lines = [
        "### 1. Отбор — по пользователям",
        "",
        "| Пользователь | касается: верно / ошибочно | не касается: верно / пропущено |",
        "|---|---|---|",
    ]
    for pid, p in sel["per"].items():
        lines.append(f"| `{pid}` | {p['tp']} / {p['fp']} | {p['tn']} / {p['fn']} |")
    lines += [
        "",
        f"Из событий, попавших в ленту хоть с какой оценкой, судья считает касающимися {sel['in_feed_tp']}"
        f", не касающимися — {sel['in_feed_fp']}.",
        "",
        "Расхождения с судьёй (до 25):",
        "",
    ]
    for e in sel["errors"][:25]:
        kind = (
            "лента показала, судья — не касается" if e["kind"] == "fp" else "судья — касается, лента скрыла"
        )
        score = "нет в ленте" if e["score"] is None else f"{e['score']:.2f}".replace(".", ",")
        lines.append(
            f"- `{e['persona']}` · {cut(e['title'], 90)} — {kind} (оценка {score}); судья: {cut(e['why'])}"
        )
    return "\n".join(lines)


def details_sources(sourced, ok, no_refs, bad_refs, bad_nums, bad_quotes) -> str:
    lines = [
        "### 2. Опора на источники",
        "",
        f"Проверено {len(sourced)} утверждений с меткой «факт», «банк», «данные» и цитат; подтверждено {ok}. "
        f"Без ссылок — {no_refs}, со ссылкой, которая не находится, — {bad_refs}, с числом, которого нет в "
        f"источнике по ссылке, — {bad_nums}, цитат, которых нет во фрагменте дословно, — {bad_quotes}.",
        "",
        "Примеры неподтверждённых (до 15):",
        "",
    ]
    shown = 0
    for b, s in sourced:
        c = s["check"]
        if c["ok"] or shown >= 15:
            continue
        why = []
        if c["no_refs"]:
            why.append("нет ссылок")
        if c["missing_refs"]:
            why.append("ссылка не находится: " + ", ".join(c["missing_refs"][:2]))
        if c["unfounded"]:
            why.append("нет в источнике: " + ", ".join(c["unfounded"][:4]))
        if not c["quote_ok"]:
            why.append("цитаты нет во фрагменте")
        lines.append(f"- `{b['persona']}` · {s['origin']} · «{cut(s['text'])}» — {'; '.join(why)}")
        shown += 1
    return "\n".join(lines)


def details_coverage(cov) -> str:
    lines = [
        "### 3. Числа охвата и уровень: лента и карточка",
        "",
        "| Событие | Пользователь | Уровень в ленте → в карточке | Счёт компаний | Числа ленты в карточке |",
        "|---|---|---|---|---|",
    ]
    for c in cov:
        counts = "сходится" if c["counts_ok"] else "; ".join(cut(x, 60) for x in c["bad"][:3])
        lost = "все" if c["feed_numbers_in_card"] else "нет: " + ", ".join(c["lost"][:4])
        if not c["feed_numbers"]:
            lost = "в выводе ленты чисел нет"
        lines.append(
            f"| {cut(c['title'], 70)} | `{c['persona']}` | {LEVEL_RU.get(c['feed_level'])} → "
            f"{LEVEL_RU.get(c['card_level'])} | {counts} | {lost} |"
        )
    return "\n".join(lines)


def details_bank(bank_items, no_bank) -> str:
    lines = ["### 4. Позиция банка", "", "Не по теме события (по мнению судьи):", ""]
    off = [(b, s) for b, s in bank_items if not s["on_topic"]]
    for b, s in off[:15]:
        lines.append(
            f"- {cut(b['insight']['event']['title'], 80)} · `{b['persona']}` — «{cut(s['text'], 120)}»; "
            f"{cut(s['why'], 100)}"
        )
    if not off:
        lines.append("- нет")
    lines += ["", "Карточки, где сказано «позиции банка нет»:", ""]
    for b in no_bank:
        j = b["bank_judge"]
        verdict = "верно" if not j["exists"] else f"позиция была: `{j.get('match')}`"
        lines.append(
            f"- {cut(b['insight']['event']['title'], 80)} · `{b['persona']}` — {verdict}; {cut(j['why'], 100)}"
        )
    return "\n".join(lines)


def details_fab(fab, unknown, with_numbers) -> str:
    lines = [
        "### 5. Выдумки — кандидаты",
        "",
        f"Утверждений с числами — {len(with_numbers)}, из них с числом, которого нет в данных, — {len(fab)}:",
        "",
    ]
    for b, s in fab[:25]:
        lines.append(
            f"- `{b['persona']}` · {s['block']} · {s['origin']} · «{cut(s['text'])}» — "
            f"{', '.join(s['fabricated_numbers'][:5])}"
        )
    if not fab:
        lines.append("- нет")
    lines += ["", "Названия и имена, которых нет в данных:", ""]
    for b, s in unknown[:20]:
        lines.append(f"- `{b['persona']}` · «{cut(s['text'], 110)}» — {', '.join(s['unknown_names'][:5])}")
    if not unknown:
        lines.append("- нет")
    return "\n".join(lines)


def details_time(fresh, journal) -> str:
    lines = [
        "### 6. Время и стоимость",
        "",
        "| Вид разбора | Сборок | Время: медиана / p90 | Стоимость: медиана / p90 | Всего |",
        "|---|---|---|---|---|",
    ]
    for kind, label in (("feed", "событие из ленты"), ("reference", "эталон"), ("unseen", "новая новость")):
        rows = [b for b in fresh if b["kind"] == kind]
        if not rows:
            continue
        s = [b["seconds"] for b in rows]
        c = [b["cost_rub"] for b in rows]
        lines.append(
            f"| {label} | {len(rows)} | {quantile(s, 0.5):.0f} / {quantile(s, 0.9):.0f} с | "
            f"{quantile(c, 0.5):.2f} / {quantile(c, 0.9):.2f} ₽ | {sum(c):.2f} ₽ |".replace(".", ",")
        )
    if journal:
        lines += [
            "",
            "Журнал вызовов моделей стенда замера (оплаченные вызовы):",
            "",
            "| Шаг | Модель | Вызовов | Время: медиана / p90 | Стоимость: медиана / сумма |",
            "|---|---|---|---|---|",
        ]
        groups: dict[tuple, list] = {}
        for j in journal:
            groups.setdefault((j["step"], j["model"]), []).append(j)
        for (step, model), rows in sorted(groups.items()):
            s = [r["seconds"] for r in rows]
            c = [r["cost"] for r in rows]
            lines.append(
                f"| {step} | {model} | {len(rows)} | {quantile(s, 0.5):.1f} / {quantile(s, 0.9):.1f} с | "
                f"{statistics.median(c):.3f} / {sum(c):.2f} ₽ |".replace(".", ",")
            )
    return "\n".join(lines)


def details_unseen(unseen, scored) -> str:
    by_id = {id(b): sc for b, sc in scored}
    lines = [
        "### 7. Новые новости",
        "",
        "| Случай | Пользователь | Ответ | Итог карточки | Чисел без опоры |",
        "|---|---|---|---|---|",
    ]
    for b in unseen:
        insight = b.get("insight")
        if not insight:
            lines.append(
                f"| {b.get('case')} | `{b['persona']}` | {b.get('status')}: {cut(b.get('error') or '', 80)} "
                f"| — | — |"
            )
            continue
        verdict = insight.get("verdict") or {}
        sc = by_id.get(id(b)) or {"statements": []}
        fab = sum(len(s.get("fabricated_numbers") or []) for s in sc["statements"])
        lines.append(
            f"| {b.get('case')} | `{b['persona']}` | {b['status']}, {b['seconds']:.0f} с | "
            f"{LEVEL_RU.get(verdict.get('level'))}: {cut(verdict.get('headline') or '', 110)} | {fab} |"
        )
    return "\n".join(lines)


def details_refs(refs) -> str:
    lines = ["### Эталоны — чек-лист", ""]
    for b in refs:
        ok = sum(c["ok"] for c in b["checklist"])
        lines.append(f"**{b['case']}** (`{b['persona']}`) — {ok} из {len(b['checklist'])}")
        for c in b["checklist"]:
            lines.append(f"- {'✔' if c['ok'] else '✘'} {c['item']} — {cut(c['why'], 120)}")
        lines.append("")
    return "\n".join(lines).rstrip()
