// Главная «Новости» по макету «A+ · Новости · главная» (лист «0 · Версии», 07_feedback §2): «Главное за день»
// (уровень → вывод → почему с числом → что делать), позиция Альфа-Банка с одной красной кнопкой и лента событий
// с картинками. Чистые функции: данные API → модель экрана (06_ui_state.md).
import type { Briefing, CompanyExposure, FeedItem, Insight, Takeaway } from '../api/types.ts';
import {
  bankCaption,
  bankSourceOf,
  factorShort,
  groupKeyOf,
  humanize,
  isHypothesis,
  leadingNumber,
  longDate,
  MAIN,
  MINOR,
  shortDate,
  topicOf,
} from './screens.ts';

export type Level = Takeaway['level'];

export const LEVEL_LABEL: Record<Level, string> = { act: 'Важно', watch: 'Следить', info: 'К сведению' };

export interface DayRow {
  eventId: string;
  level: Level;
  /** вывод: важно ли и почему — одной фразой */
  headline: string;
  /** заголовок — вывод модели (иначе это заголовок новости, факт) */
  fromModel: boolean;
  /** почему, с числом из данных */
  why: string;
  /** что делать — только когда это есть в разборе */
  todo: string | null;
}

export interface EventRow {
  eventId: string;
  factor: string;
  imageUrl: string | null;
  iconUrl: string | null;
  /** «Банк России · ещё 2 материала · 23.10» */
  sourceLine: string;
  title: string;
  level: Level;
  why: string;
  /** позиция банка одной строкой — только из собранного разбора */
  bank: string | null;
}

export interface NewsScreen {
  /** «24 октября · обновлено в 12:54» */
  updated: string;
  day: DayRow[];
  bank: { statement: string; caption: string; eventId: string } | null;
  action: { eventId: string; label: string; topic: string } | null;
  chips: { key: string | null; label: string; count: number; selected: boolean }[];
  events: EventRow[];
  /** сколько событий под «Показать ещё» */
  more: number;
  /** разбор главного события — для вопросов */
  leadInsight: Insight | null;
  empty: boolean;
}

export interface NewsState {
  feed: Briefing;
  exposure: CompanyExposure | null;
  hidden: string[];
  /** фильтр ленты по теме (ключ фактора); null — все */
  filter: string | null;
  /** показать все события, а не первые */
  showAll: boolean;
  /** разбор главного события, если уже собран (cached=true) */
  lead: Insight | null;
  today: string;
}

const DAY_ROWS = 3;
const FIRST_EVENTS = 4;

export function levelOf(item: FeedItem): Level {
  if (item.takeaway?.level) return item.takeaway.level;
  return item.relevance.score >= MAIN ? 'act' : item.relevance.score >= MINOR ? 'watch' : 'info';
}

/** Уровень с учётом разбора: итог разбора главнее оценки ленты — один уровень на всех экранах. */
export function levelWith(item: FeedItem | null, insight: Insight | null): Level {
  if (insight?.verdict?.level) return insight.verdict.level;
  if (item) return levelOf(item);
  const score = insight?.relevance.score ?? 0;
  return score >= MAIN ? 'act' : score >= MINOR ? 'watch' : 'info';
}

/**
 * Убрать технические обороты из текста для руководителя (07_feedback §1): «по карте чувствительности …» →
 * «у компании …». Смысл не меняется — только слова, которых пользователь не знает.
 */
const MAP_CASES: [RegExp, string][] = [
  [/картой чувствительности/gi, 'данными банка о компании'],
  [/карте чувствительности/gi, 'данных банка о компании'],
  [/карту чувствительности/gi, 'данные банка о компании'],
  [/карты чувствительности/gi, 'данных банка о компании'],
  [/карта чувствительности/gi, 'данные банка о компании'],
];

export function plain(text: string): string {
  let out = text
    .replace(/^по карте чувствительности,?\s*/i, '')
    .replace(/\s*по карте чувствительности,?\s*/gi, ' ');
  for (const [re, to] of MAP_CASES) out = out.replace(re, to);
  out = out.trim();
  return out ? out[0].toUpperCase() + out.slice(1) : text;
}

/** Почему это важно: вывод API, иначе короткая строка из данных, иначе очищенный канал. */
export function whyOf(item: FeedItem): string {
  return plain(item.takeaway?.text || item.short || humanize(item.channel_text || item.relevance.reason));
}

/** Цепочка: событие → фактор → число из данных компании → Вы. Только то, что есть в данных. */
export function chainOf(items: FeedItem[], exposure: CompanyExposure | null): string[] {
  const lead = items[0];
  const f = lead.factors[0];
  const code = f?.code ?? '';
  const factor = exposure?.factors.find((x) => x.code === code);
  const evidence = factor?.evidence.map((e) => ({ e, n: leadingNumber(e.value) })).find((x) => x.n);
  const nodes = [
    factorShort(code, f?.label ?? 'Своя отрасль'),
    factor ? factor.label : null,
    evidence ? `${humanize(evidence.e.label)} · ${evidence.n}` : null,
  ].filter((x): x is string => Boolean(x));
  const unique = nodes.filter(
    (x, i) => !nodes.some((y, j) => j !== i && (j < i ? y.toLowerCase() === x.toLowerCase() : y.toLowerCase().startsWith(x.toLowerCase()))),
  );
  return [...unique, 'Вы'];
}

function groupsOf(items: FeedItem[]): FeedItem[][] {
  const map = new Map<string, FeedItem[]>();
  for (const i of [...items].sort((a, b) => b.relevance.score - a.relevance.score)) {
    const k = groupKeyOf(i);
    map.set(k, [...(map.get(k) ?? []), i]);
  }
  return [...map.values()];
}

function sourceLineOf(group: FeedItem[]): string {
  const top = group[0];
  const publisher = top.source.publisher ?? (top.source.kind === 'alfa_analytics' ? 'Альфа-Банк' : 'Источник');
  const extra = group.length - 1;
  return [
    publisher,
    extra > 0 ? `ещё ${extra} по теме` : null,
    shortDate(top.event.date ?? top.source.published_at),
  ]
    .filter(Boolean)
    .join(' · ');
}

/** Позиция банка из разбора: «Альфа-Банк ожидает …» и подпись аналитиков с материалом и датой. */
export function bankOf(ins: Insight): { statement: string; caption: string } | null {
  const b = ins.bank_view[0];
  const statement = ins.bank_position?.statement ?? b?.text ?? null;
  if (!statement) return null;
  const src = b ? b.refs.map((r) => bankSourceOf(ins, r)).find((x) => x !== undefined)?.source : undefined;
  return { statement: plain(statement), caption: bankCaption(src) };
}

/** Главные события дня: лучшее событие каждой темы значимостью от 0,3, не больше трёх. Те же — на плашке банка. */
export function dayItems(items: FeedItem[]): FeedItem[] {
  return groupsOf(items)
    .filter((g) => g[0].relevance.score >= MINOR)
    .slice(0, DAY_ROWS)
    .map((g) => g[0]);
}

export function newsScreen(s: NewsState): NewsScreen {
  const visible = s.feed.items.filter((i) => !s.hidden.includes(i.event_id));
  const groups = groupsOf(visible);
  const lead = groups[0]?.[0] ?? null;
  const ins = s.lead && lead ? s.lead : null;

  // «Главное за день»: три главные темы; у главной — вывод и «что делать» из разбора, если он собран.
  const day: DayRow[] = dayItems(visible).map((top, idx) => {
      const fromInsight = idx === 0 ? ins : null;
      const model = fromInsight
        ? (fromInsight.verdict?.headline ?? fromInsight.why_it_matters.find((x) => x.origin === 'ai' && !isHypothesis(x))?.text ?? null)
        : null;
      const todo = fromInsight
        ? (fromInsight.verdict?.actions?.[0] ?? fromInsight.actions.find((a) => a.kind !== 'product')?.text ?? null)
        : null;
      return {
        eventId: top.event_id,
        level: levelWith(top, fromInsight),
        headline: plain(model ?? top.event.title),
        fromModel: model !== null,
        why: whyOf(top),
        todo: todo ? plain(todo) : null,
      };
    });

  const bankLead = ins ? bankOf(ins) : null;
  const bank = bankLead && lead ? { ...bankLead, eventId: lead.event_id } : null;
  const action =
    lead && lead.relevance.score >= MAIN
      ? { eventId: lead.event_id, topic: topicOf(groupKeyOf(lead)), label: `Обсудить ${topicOf(groupKeyOf(lead))} с менеджером` }
      : null;

  // Фильтр по теме, которой у этого пользователя нет (сменили пользователя, всё скрыто), не действует.
  const filter = s.filter && groups.some((g) => groupKeyOf(g[0]) === s.filter) ? s.filter : null;
  const chips = [
    { key: null, label: 'Все', count: groups.length, selected: filter === null },
    ...groups.map((g) => ({
      key: groupKeyOf(g[0]),
      label: factorShort(groupKeyOf(g[0]), g[0].factors[0]?.label),
      count: g.length,
      selected: filter === groupKeyOf(g[0]),
    })),
  ];
  // При выборе темы — все её события по отдельности; без фильтра — по одному на тему.
  const filtered = filter ? groups.filter((g) => groupKeyOf(g[0]) === filter).flatMap((g) => g.map((i) => [i])) : groups;
  const rows: EventRow[] = filtered.map((g) => {
    const top = g[0];
    const isLead = lead !== null && top.event_id === lead.event_id;
    return {
      eventId: top.event_id,
      factor: top.factors[0]?.code ?? 'industry',
      imageUrl: top.image_url ?? null,
      iconUrl: top.source_icon_url ?? null,
      sourceLine: sourceLineOf(g),
      title: top.event.title,
      level: levelWith(top, isLead ? ins : null),
      why: whyOf(top),
      bank: isLead && bankLead ? bankLead.statement : null,
    };
  });
  const shown = s.showAll || filter ? rows : rows.slice(0, FIRST_EVENTS);

  // Время сборки лента не отдаёт — показываем время последней новости в местном поясе.
  const last = [...visible]
    .map((i) => i.source.published_at ?? '')
    .filter((d) => d.length > 10)
    .map((d) => new Date(d))
    .filter((d) => !Number.isNaN(d.getTime()))
    .sort((a, b) => a.getTime() - b.getTime())
    .pop();
  const lastText = last
    ? `последняя новость — ${String(last.getDate()).padStart(2, '0')}.${String(last.getMonth() + 1).padStart(2, '0')}, ${String(last.getHours()).padStart(2, '0')}:${String(last.getMinutes()).padStart(2, '0')}`
    : null;
  const updated = [longDate(s.today), lastText].filter(Boolean).join(' · ');

  return {
    updated,
    day,
    bank,
    action,
    chips,
    events: shown,
    more: rows.length - shown.length,
    leadInsight: ins,
    empty: visible.length === 0,
  };
}

/** Поиск по ленте пользователя: все слова запроса — в заголовке, источнике, теме или выводе. */
export function matchFeed(items: FeedItem[], query: string): FeedItem[] {
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  if (words.length === 0) return [];
  return items.filter((i) => {
    const hay = [i.event.title, i.source.publisher, i.channel_text, i.short, ...i.factors.map((f) => f.label)]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return words.every((w) => hay.includes(w.slice(0, Math.max(4, w.length - 2))));
  });
}
