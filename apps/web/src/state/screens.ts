// Интерфейс = f(состояние) (team/docs/06_ui_state.md): чистые функции «данные API + действия пользователя →
// модель экрана». Компоненты только рисуют модель; одинаковое состояние даёт одинаковый экран.
// Здесь только типы из API — модуль проверяется тестами без сборки (node --test).
import type {
  Action,
  Briefing,
  CompanyExposure,
  ExposureFactor,
  FeedItem,
  Insight,
  Role,
  Source,
  Statement,
} from '../api/types';

// ─── общие ────────────────────────────────────────────────────────────────────

/** Короткие названия факторов для меток групп и фильтров; нет в словаре — берём название из данных. */
const FACTOR_SHORT: Record<string, string> = {
  rate: 'Ставка',
  fx: 'Курс',
  ved_logistics: 'ВЭД и логистика',
  inflation: 'Инфляция',
  consumer: 'Спрос',
  labor: 'Рынок труда',
  tax_regulation: 'Налоги и регулирование',
  gov: 'Госзаказ',
  oil: 'Нефть',
  gold: 'Золото',
  deposit: 'Депозиты',
  industry: 'Своя отрасль',
};

export const INDUSTRY = 'industry';

export function factorShort(code: string, fallback?: string): string {
  return FACTOR_SHORT[code] ?? fallback ?? code;
}

/** Склонение: plural(3, ['событие', 'события', 'событий']). */
export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b === 1) return forms[0];
  if (b >= 2 && b <= 4) return forms[1];
  return forms[2];
}

/** «23.10» из даты ISO; без даты — пусто. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}` : '';
}

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

function longDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : iso;
}

/** Монограмма источника вместо логотипа издания: «ЦБ», «Ъ». Для аналитики банка — null (рисуем иконку банка). */
export function sourceMark(source: Pick<Source, 'kind' | 'publisher'>): string | null {
  if (source.kind === 'alfa_analytics') return null;
  const p = (source.publisher ?? '').trim();
  const known: Record<string, string> = {
    'Банк России': 'ЦБ',
    'ЦБ РФ': 'ЦБ',
    Коммерсантъ: 'Ъ',
    РБК: 'РБК',
    Интерфакс: 'ИФ',
    ТАСС: 'ТАСС',
    Ведомости: 'В',
    Forbes: 'F',
    'РИА Новости': 'РИА',
    Росстат: 'РС',
    Минфин: 'МФ',
  };
  if (known[p]) return known[p];
  const words = p.split(/[\s-]+/).filter(Boolean);
  if (words.length === 0) return '·';
  return words
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('');
}

// ─── лента ────────────────────────────────────────────────────────────────────

/** Сколько заголовков группы видно сразу; остальные — по «Ещё N материалов». */
export const GROUP_HEADLINES = 3;

/** Пороги значимости из 06_ui_state.md: главное ≥ 0,6, важное ≥ 0,3, ниже — свёрнуто. */
export const MAIN = 0.6;
export const MINOR = 0.3;

const BRIEF_ROLES: Role[] = ['owner', 'ceo'];

export interface FeedHeadline {
  eventId: string;
  title: string;
  mark: string | null;
  sourceLine: string;
  isNew: boolean;
}

export interface FeedGroup {
  key: string;
  label: string;
  /** капс-метка «Ставка · 3 материала · 23.10» */
  caps: string;
  isNew: boolean;
  score: number;
  headlines: FeedHeadline[];
  /** одна фраза «для вас» на группу — не повторяем её у каждой новости */
  forYou: string;
  hasBankView: boolean;
  /** какой разбор открывать: самое значимое событие группы */
  openEventId: string;
}

export interface Indicator {
  code: string;
  label: string;
  value: string;
  note: string;
}

export type FeedTop =
  | { kind: 'indicators'; items: Indicator[] }
  | { kind: 'brief'; points: { eventId: string; title: string; forYou: string }[] };

export interface FeedScreen {
  headline: string;
  top: FeedTop | null;
  chips: { key: string | null; label: string; count: number; selected: boolean }[];
  groups: FeedGroup[];
  /** события меньшей значимости: свёрнуты или развёрнуты «Показать» */
  collapsed: { count: number; titles: string[]; expanded: boolean } | null;
  hiddenCount: number;
  empty: boolean;
}

export interface FeedState {
  feed: Briefing;
  exposure: CompanyExposure | null;
  role: Role;
  hidden: string[];
  /** фильтр по группе (ключ фактора); null — все */
  filter: string | null;
  /** дата прошлого визита (ISO); null — первый визит */
  lastVisit: string | null;
  /** развернуть свёрнутые события меньшей значимости */
  showAll: boolean;
}

export function groupKeyOf(item: FeedItem): string {
  return item.factors[0]?.code ?? INDUSTRY;
}

function groupLabel(item: FeedItem): string {
  const f = item.factors[0];
  return f ? factorShort(f.code, f.label) : factorShort(INDUSTRY);
}

function isNewItem(item: FeedItem, lastVisit: string | null): boolean {
  const date = item.event.date ?? item.source.published_at ?? null;
  if (!date) return false;
  return lastVisit === null ? false : date.slice(0, 10) > lastVisit.slice(0, 10);
}

function sourceLine(item: FeedItem): string {
  const publisher = item.source.publisher ?? (item.source.kind === 'alfa_analytics' ? 'Альфа-Банк' : 'Источник');
  const at = item.source.published_at ?? item.event.date;
  const time = at && at.length > 10 ? `, ${at.slice(11, 16)}` : '';
  return `${publisher} · ${shortDate(at)}${time}`;
}

function buildGroups(items: FeedItem[], lastVisit: string | null): FeedGroup[] {
  const map = new Map<string, FeedItem[]>();
  for (const item of items) {
    const key = groupKeyOf(item);
    map.set(key, [...(map.get(key) ?? []), item]);
  }
  const groups = [...map.entries()].map(([key, list]): FeedGroup => {
    const sorted = [...list].sort((a, b) => b.relevance.score - a.relevance.score);
    const top = sorted[0];
    const iso = [...new Set(sorted.map((i) => (i.event.date ?? '').slice(0, 10)).filter(Boolean))].sort();
    const first = shortDate(iso[0]);
    const last = shortDate(iso[iso.length - 1]);
    const range =
      iso.length > 1 ? `${first.slice(3) === last.slice(3) ? first.slice(0, 2) : first}–${last}` : first;
    const n = sorted.length;
    return {
      key,
      label: groupLabel(top),
      caps: [groupLabel(top), `${n} ${plural(n, ['материал', 'материала', 'материалов'])}`, range].filter(Boolean).join(' · '),
      isNew: sorted.some((i) => isNewItem(i, lastVisit)),
      score: top.relevance.score,
      headlines: sorted.map((i) => ({
        eventId: i.event_id,
        title: i.event.title,
        mark: sourceMark(i.source),
        sourceLine: sourceLine(i),
        isNew: isNewItem(i, lastVisit),
      })),
      forYou: top.channel_text || top.relevance.reason,
      hasBankView: sorted.some((i) => i.has_bank_view),
      openEventId: top.event_id,
    };
  });
  return groups.sort((a, b) => b.score - a.score);
}

/** Три показателя для финансовых ролей: факторы ленты с наибольшей силой, значение — из данных банка. */
function indicators(groups: FeedGroup[], exposure: CompanyExposure | null): Indicator[] {
  if (!exposure) return [];
  const inFeed = new Set(groups.map((g) => g.key));
  return exposure.factors
    .filter((f): f is ExposureFactor & { strength: number } => inFeed.has(f.code) && (f.strength ?? 0) > 0)
    .sort((a, b) => b.strength - a.strength)
    .slice(0, 3)
    .map((f) => {
      // Значение — первое число из данных банка («11 из 28», «44 %»); чисел нет — словами сила связи.
      const numeric = f.evidence.map((e) => ({ e, n: leadingNumber(e.value) })).find((x) => x.n);
      return {
        code: f.code,
        label: f.label,
        value: numeric?.n ?? LEVEL_WORD[f.level] ?? '',
        note: numeric ? numeric.e.label : (f.channel?.text ?? ''),
      };
    });
}

/** Ведущее число значения с единицей: «44 % всех платежей…» → «44 %», «11 из 28» → «11 из 28»; коды ОКВЭД — не числа. */
export function leadingNumber(value: string): string | null {
  const m = /^\d[\d\s]*(?:,\d+)?(?![.\d])(?:\s?(?:%|млрд ₽|млн ₽|тыс\. ₽|₽|из \d+|[а-яё]+))?/.exec(value.trim());
  return m ? m[0].trim() : null;
}

const LEVEL_WORD: Record<string, string> = {
  high: 'сильная связь',
  medium: 'средняя связь',
  low: 'слабая связь',
  none: 'связи нет',
  no_data: 'нет данных',
};

/**
 * Одна и та же фраза «для вас» у разных групп не повторяется: повтор заменяем каналом фактора группы из карты
 * чувствительности (или его доказательством); если и они совпадают — оставляем как есть.
 */
function distinctForYou(groups: FeedGroup[], exposure: CompanyExposure | null): FeedGroup[] {
  const used = new Set<string>();
  return groups.map((g) => {
    let forYou = g.forYou;
    if (used.has(forYou)) {
      const f = exposure?.factors.find((x) => x.code === g.key);
      const alt = [f?.channel?.text, f?.evidence[0] ? `${f.evidence[0].label}: ${f.evidence[0].value}` : null].find(
        (t): t is string => Boolean(t) && !used.has(t as string),
      );
      if (alt) forYou = alt;
    }
    used.add(forYou);
    return forYou === g.forYou ? g : { ...g, forYou };
  });
}

export function feedScreen(s: FeedState): FeedScreen {
  const visible = s.feed.items.filter((i) => !s.hidden.includes(i.event_id));
  const allGroups = distinctForYou(buildGroups(visible, s.lastVisit), s.exposure);
  const hiddenCount = s.feed.items.length - visible.length;

  const chips = [
    { key: null, label: 'Все', count: visible.length, selected: s.filter === null },
    ...allGroups.map((g) => ({ key: g.key, label: g.label, count: g.headlines.length, selected: s.filter === g.key })),
  ];
  // Сворачиваются события значимостью ниже 0,3 (а не целые группы); фильтр по фактору показывает всё.
  const pool = s.filter ? visible.filter((i) => groupKeyOf(i) === s.filter) : visible;
  const low = s.filter ? [] : pool.filter((i) => i.relevance.score < MINOR);
  const main = s.showAll ? pool : pool.filter((i) => !low.includes(i));
  const shown = distinctForYou(buildGroups(main, s.lastVisit), s.exposure);

  const fresh = visible.filter((i) => isNewItem(i, s.lastVisit)).length;
  const important = visible.filter((i) => i.relevance.score >= MAIN).length;
  const total = `${visible.length} ${plural(visible.length, ['событие', 'события', 'событий'])}`;
  const headline =
    (s.lastVisit
      ? `С ${longDate(s.lastVisit)}: ${fresh} ${plural(fresh, ['новое событие', 'новых события', 'новых событий'])} · всего в ленте ${total}`
      : `В ленте для вас ${total}`) + (important > 0 ? ` · главных ${important}` : '');

  let top: FeedTop | null = null;
  if (BRIEF_ROLES.includes(s.role)) {
    const points = allGroups.slice(0, 3).map((g) => ({ eventId: g.openEventId, title: g.headlines[0].title, forYou: g.forYou }));
    top = points.length ? { kind: 'brief', points } : null;
  } else {
    const items = indicators(allGroups, s.exposure);
    top = items.length ? { kind: 'indicators', items } : null;
  }

  return {
    headline,
    top,
    chips,
    groups: shown,
    collapsed: low.length ? { count: low.length, titles: low.map((i) => i.event.title), expanded: s.showAll } : null,
    hiddenCount,
    empty: visible.length === 0,
  };
}

// ─── карточка ─────────────────────────────────────────────────────────────────

/** Тема разговора с менеджером по фактору события. */
const TOPIC: Record<string, string> = {
  rate: 'структуру долга',
  fx: 'валютный риск',
  ved_logistics: 'расчёты по ВЭД',
  inflation: 'рост издержек',
  consumer: 'спрос и оборотный капитал',
  tax_regulation: 'налоговые изменения',
  labor: 'фонд оплаты труда',
  deposit: 'размещение свободных средств',
};

const PRODUCT_LABEL: Record<string, string> = {
  rko: 'расчётного счёта',
  guarantee: 'гарантии',
  credit: 'кредита',
  leasing: 'лизинга',
  deposit: 'депозита',
  salary_project: 'зарплатного проекта',
  factoring: 'факторинга',
  fx: 'валютного контроля',
};

export interface CardSource {
  mark: string | null;
  label: string;
}

export interface CardRow {
  id: 'chain' | 'risks' | 'hypotheses' | 'estimates' | 'sources' | 'trace' | 'ask';
  title: string;
  summary: string;
}

export interface CardMenuItem {
  id: 'forward' | 'weekly' | 'remind' | 'product' | 'hide';
  label: string;
}

export interface CardScreen {
  crumbs: string;
  title: string;
  sources: CardSource[];
  lead: string[];
  forYou: {
    phrase: string;
    numbers: { value: string; label: string }[];
    quote: { text: string; verbatim: boolean; caption: string } | null;
  };
  /** целевое действие; null — у разбора нет риска, разговор с менеджером не предлагаем */
  target: { topic: string; prompt: string; button: string } | null;
  menu: CardMenuItem[];
  rows: CardRow[];
  hypotheses: Statement[];
  estimates: Statement[];
  /** риски, возможности и факторы без гипотез и расчётов — то, что в блоке «Риски и возможности» */
  riskItems: Statement[];
  disclaimer: string | null;
}

export interface CardState {
  insight: Insight;
  /** событие из ленты: факторы и канал; при заходе по прямой ссылке может не быть */
  item: FeedItem | null;
  exposure: CompanyExposure | null;
}

const isHypothesis = (s: Statement) => s.origin === 'hypothesis' || (s.origin === 'ai' && s.confidence === 'low');

function bankCaption(source: Source | undefined): string {
  if (!source) return 'Аналитики Альфа-Банка';
  const parts = ['Аналитики Альфа-Банка', `«${source.title}»`];
  if (source.published_at) parts.push(shortDate(source.published_at) + '.' + source.published_at.slice(0, 4));
  if (source.page) parts.push(`стр. ${source.page}`);
  return parts.join(' · ');
}

/** Источник-аналитика банка по ссылке. Цитатой считается только fragment страницы, на которую ссылаемся. */
function bankSourceOf(insight: Insight, ref: string): { source: Source; exact: boolean } | undefined {
  const bank = insight.sources.filter((s) => s.kind === 'alfa_analytics');
  const exact = bank.find((s) => s.id === ref);
  if (exact) return { source: exact, exact: true };
  const material = bank.find((s) => s.id === ref.split('#')[0]);
  return material ? { source: material, exact: false } : undefined;
}

export function cardScreen({ insight, item, exposure }: CardState): CardScreen {
  const codes = item?.factors.map((f) => f.code) ?? [];
  const groupName = item ? groupLabel(item) : 'Разбор';

  // Источники-новости монограммами: одно издание — одна монограмма, у нескольких статей — их число.
  const news = insight.sources.filter((s) => s.kind === 'news');
  const byPublisher = new Map<string, Source[]>();
  for (const s of news) {
    const key = s.publisher ?? s.title;
    byPublisher.set(key, [...(byPublisher.get(key) ?? []), s]);
  }
  const sources = [...byPublisher.entries()].map(([publisher, list]) => ({
    mark: sourceMark(list[0]),
    label:
      list.length > 1
        ? `${publisher} · ${list.length} ${plural(list.length, ['статья', 'статьи', 'статей'])}`
        : `${publisher}${list[0].published_at ? ` · ${shortDate(list[0].published_at)}` : ''}`,
  }));

  const numbers = exposure
    ? exposure.factors
        .filter((f) => codes.includes(f.code))
        .flatMap((f) => f.evidence.map((e) => ({ value: leadingNumber(e.value), label: e.label })))
        .filter((x): x is { value: string; label: string } => x.value !== null)
        .slice(0, 2)
    : [];

  const bank = insight.bank_view[0];
  const found = bank ? bank.refs.map((r) => bankSourceOf(insight, r)).filter((x) => x !== undefined) : [];
  const exact = found.find((x) => x.exact && x.source.fragment);
  const bankSource = exact?.source ?? found[0]?.source;
  const quote = bank
    ? exact?.source.fragment
      ? { text: `«${exact.source.fragment.trim()}»`, verbatim: true, caption: bankCaption(bankSource) }
      : { text: bank.text, verbatim: false, caption: bankCaption(bankSource) }
    : null;

  const { risks, opportunities, factors } = insight.consequences;
  const all = [...insight.why_it_matters, ...risks, ...opportunities, ...factors];
  const hypotheses = all.filter(isHypothesis);
  const estimates = all.filter((s) => s.origin === 'estimate');
  const conflicts = hypotheses.filter((s) => s.bank_conflict).length;
  const product = insight.actions.find((a: Action) => a.kind === 'product' && a.product);

  const topic = TOPIC[codes[0] ?? ''] ?? 'последствия для компании';
  const target =
    risks.length > 0
      ? {
          topic,
          prompt: `Обсудить с менеджером ${topic}? Контекст разбора подставим в обращение.`,
          button: 'Обсудить с менеджером',
        }
      : null;

  const menu: CardMenuItem[] = [
    { id: 'forward', label: 'Переслать коллеге' },
    { id: 'weekly', label: 'Добавить в сводку недели' },
    { id: 'remind', label: 'Напомнить через неделю' },
  ];
  if (product?.product) menu.push({ id: 'product', label: `Проверить условия ${PRODUCT_LABEL[product.product] ?? 'продукта'}` });
  menu.push({ id: 'hide', label: 'Скрыть: не про нас' });

  const plain = (s: Statement) => !isHypothesis(s) && s.origin !== 'estimate';
  const riskItems = [...risks, ...opportunities, ...factors].filter(plain);
  const nRisk = risks.filter(plain).length;
  const nOpp = opportunities.filter(plain).length;
  const rows: CardRow[] = [
    { id: 'chain', title: 'Через кого вас задевает', summary: item?.channel_text || insight.relevance.reason },
    {
      id: 'risks',
      title: 'Риски и возможности',
      summary: `${nRisk} ${plural(nRisk, ['риск', 'риска', 'рисков'])}, ${nOpp} ${plural(nOpp, ['возможность', 'возможности', 'возможностей'])}`,
    },
  ];
  if (hypotheses.length)
    rows.push({
      id: 'hypotheses',
      title: 'Гипотезы',
      summary: `${hypotheses.length}${conflicts ? ` · ${conflicts} ${plural(conflicts, ['расходится', 'расходятся', 'расходятся'])} с банком` : ''}`,
    });
  rows.push({
    id: 'estimates',
    title: 'Расчёт в рублях',
    summary: estimates.length ? `${estimates.length} ${plural(estimates.length, ['расчёт', 'расчёта', 'расчётов'])}` : 'в разборе нет',
  });
  rows.push({
    id: 'sources',
    title: 'Источники',
    summary: `${insight.sources.length} ${plural(insight.sources.length, ['материал', 'материала', 'материалов'])} · ${insight.features_used.length} ${plural(insight.features_used.length, ['признак', 'признака', 'признаков'])} компании`,
  });
  if (insight.trace_id) rows.push({ id: 'trace', title: 'Как получен вывод', summary: 'шаги агента и проверки' });
  rows.push({ id: 'ask', title: 'Задать вопрос', summary: 'уточнить по разбору' });

  return {
    crumbs: `Лента › ${groupName}`,
    title: insight.event.title,
    sources,
    lead: insight.what_happened.slice(0, 2).map((s) => s.text),
    forYou: {
      phrase: insight.why_it_matters[0]
        ? `${isHypothesis(insight.why_it_matters[0]) ? 'Гипотеза: ' : ''}${insight.why_it_matters[0].text}`
        : insight.relevance.reason,
      numbers,
      quote,
    },
    target,
    menu,
    rows,
    hypotheses,
    estimates,
    riskItems,
    disclaimer: insight.disclaimer ?? null,
  };
}

/** Через сколько показывать целевое действие: ~15 с на посте (или при прокрутке до конца). */
export const TARGET_DELAY_MS = 15_000;
