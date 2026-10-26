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
import { readinessOf, type Readiness } from './trust.ts';

export type Level = Takeaway['level'];

export const LEVEL_LABEL: Record<Level, string> = { act: 'Важно', watch: 'На контроле', info: 'К сведению' };

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
  /** разбор собран заранее или готовится */
  ready: Readiness | null;
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
  ready: Readiness | null;
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
  // Уровень события держит лента (takeaway.level, 6 ч): бейдж в ленте и в карточке не расходятся.
  if (item?.takeaway?.level) return item.takeaway.level;
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
  // «направление пока неясно» руководителю ничего не говорит
  text = text.replace(/направление пока неясно/gi, (m) => (m[0] === 'Н' ? 'Влияние неоднозначно' : 'влияние неоднозначно'));
  let out = text
    .replace(/^по карте чувствительности,?\s*/i, '')
    .replace(/\s*по карте чувствительности,?\s*/gi, ' ');
  for (const [re, to] of MAP_CASES) out = out.replace(re, to);
  out = out.trim();
  return out ? out[0].toUpperCase() + out.slice(1) : text;
}

/** Почему это важно: вывод API, иначе короткая строка из данных, иначе очищенный канал. */
export function whyOf(item: FeedItem): string {
  return withoutLevel(plain(item.takeaway?.text || item.short || humanize(item.channel_text || item.relevance.reason)));
}

/** Вывод API иногда начинается со своей метки уровня («Важно: …») — на экране метка уже есть, второй раз не пишем. */
export function withoutLevel(text: string): string {
  const out = text.replace(/^(?:важно|следить|стоит следить|на контроле|к сведению)\s*:\s*/i, '');
  return out ? out[0].toUpperCase() + out.slice(1) : text;
}

/** Вывод API пишет действие в конце: «… Что делать: сверьте сроки». В макете это отдельная строка. */
export function splitTodo(text: string | null): { why: string | null; todo: string | null } {
  if (!text) return { why: null, todo: null };
  const m = /^(.*?)[\s.]*Что делать:\s*(.+)$/s.exec(text);
  const why = m?.[1].trim() ?? '';
  return why ? { why: /[.!?…]$/.test(why) ? why : `${why}.`, todo: m![2].trim() } : { why: text, todo: null };
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

const UNCONFIRMED = /не\s+удалось\s+подтвердить|подтвердить\s+не\s+удалось|нет\s+позиции/i;

/** Позиция банка из разбора: «Альфа-Банк ожидает …» и подпись аналитиков с материалом и датой. */
export function bankOf(ins: Insight): { statement: string; caption: string } | null {
  const b = ins.bank_view[0];
  // «Позицию Альфа-Банка подтвердить не удалось» — это не позиция банка: ни красной цитаты, ни подписи аналитиков;
  // есть настоящая цитата в bank_view — берём её.
  const own = ins.bank_position?.statement ?? null;
  const statement = own && !UNCONFIRMED.test(own) ? own : b?.text && !UNCONFIRMED.test(b.text) ? b.text : null;
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
      // «Что делать» в выводе ленты — отдельной строкой; из разбора — главнее.
      const split = splitTodo(whyOf(top));
      return {
        eventId: top.event_id,
        level: levelWith(top, fromInsight),
        headline: plain(model ?? top.event.title),
        fromModel: model !== null,
        why: split.why ?? whyOf(top),
        todo: todo ? plain(todo) : split.todo,
        ready: readinessOf(top),
      };
    });

  const bankLead = ins ? bankOf(ins) : null;
  const bank = bankLead && lead ? { ...bankLead, eventId: lead.event_id } : null;
  const action =
    lead && lead.relevance.score >= MAIN
      ? { eventId: lead.event_id, topic: topicOf(groupKeyOf(lead)), label: `Обсудить ${topicOf(groupKeyOf(lead))} с менеджером` }
      : null;

  // Фильтр по фактору: событие подходит, если задевает фактор хоть как-то, а не только главным. Фактора, которого
  // в ленте этого пользователя нет (сменили пользователя, всё скрыто), фильтр не действует.
  // «Своя отрасль» — события без факторов: у них ключ группы industry.
  const touches = (i: FeedItem, code: string) => groupKeyOf(i) === code || i.factors.some((f) => f.code === code);
  const countOf = (code: string) => visible.filter((i) => touches(i, code)).length;
  const filter = s.filter && visible.some((i) => touches(i, s.filter as string)) ? s.filter : null;
  const chips = [
    { key: null, label: 'Все', count: groups.length, selected: filter === null },
    ...groups.map((g) => ({
      key: groupKeyOf(g[0]),
      label: factorShort(groupKeyOf(g[0]), g[0].factors[0]?.label),
      count: countOf(groupKeyOf(g[0])),
      selected: filter === groupKeyOf(g[0]),
    })),
  ];
  // Пришли с карты по фактору, который ни у одного события не главный, — у него тоже есть чип.
  if (filter && !chips.some((c) => c.key === filter)) {
    const label = visible.flatMap((i) => i.factors).find((f) => f.code === filter)?.label;
    chips.push({ key: filter, label: factorShort(filter, label), count: countOf(filter), selected: true });
  }
  // При выборе темы — все её события по отдельности; без фильтра — по одному на тему.
  const filtered = filter
    ? groups.flatMap((g) => g.filter((i) => touches(i, filter)).map((i) => [i]))
    : groups;
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
      ready: readinessOf(top),
    };
  });
  // Без фильтра события из «Главного за день» второй раз не показываем — только когда пользователь выбрал тему.
  const dayIds = new Set(day.map((d) => d.eventId));
  const rest = filter ? rows : rows.filter((r) => !dayIds.has(r.eventId));
  const shown = s.showAll || filter ? rest : rest.slice(0, FIRST_EVENTS);

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
    more: rest.length - shown.length,
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

/** Сколько событий в ленте — то же число, что пользователь увидит в «Главном» и «Событиях» (по одному на тему). */
export function feedCount(items: FeedItem[]): number {
  return groupsOf(items).length;
}
