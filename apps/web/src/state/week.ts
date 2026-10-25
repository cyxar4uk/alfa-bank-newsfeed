// «Главное за неделю» (макет B1) и «К чему уязвима компания» (макеты B2, B3): данные API → модель экрана.
// Чистые функции, как news.ts: ничего не досчитываем сверх того, что есть в ответе.
import type { BankView, Briefing, Dynamics, RiskFactor, RiskMap, RiskStrength, Story } from '../api/types.ts';
import { plain, splitTodo, type Level } from './news.ts';

export { splitTodo };
import { plural, shortDate } from './screens.ts';

export const DYNAMICS_LABEL: Record<Dynamics, string> = { appeared: 'Появился', grew: 'Усилился', faded: 'Утих', steady: 'Держится' };

const WEEKDAY_LETTER = ['В', 'П', 'В', 'С', 'Ч', 'П', 'С'];
const WEEKDAY_NAME = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

/** День недели (0 — воскресенье) из даты ISO; без даты — null. */
function weekday(iso: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))).getUTCDay() : null;
}

/** Мини-график: число новостей за день, буква дня и подпись дня для экранного диктора. */
export interface Day {
  n: number;
  letter: string;
  name: string;
}

/** Дни графика: даты из ответа API; без дат — только числа, подписи «день 1…7». */
export function daysOf(counts: number[], week: string[]): Day[] {
  // Даты подписываем, только если их столько же, сколько чисел: иначе буквы дней съедут.
  const dates = week.length === counts.length ? week : [];
  return counts.map((n, i) => {
    const wd = dates[i] ? weekday(dates[i]) : null;
    return wd === null
      ? { n, letter: '', name: `день ${i + 1}` }
      : { n, letter: WEEKDAY_LETTER[wd], name: `${WEEKDAY_NAME[wd]} ${shortDate(week[i])}` };
  });
}

export function daysLabel(days: Day[]): string {
  return `Новостей по дням: ${days.map((d) => `${d.name} — ${d.n}`).join(', ')}`;
}

/** «19–25 октября», «28 сентября – 4 октября»; без дат — пусто. */
export function periodText(week: string[]): string {
  const parse = (iso: string | undefined) => {
    const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
    return m ? { m: Number(m[2]), d: Number(m[3]) } : null;
  };
  const a = parse(week[0]);
  const b = parse(week[week.length - 1]);
  if (!a || !b) return '';
  return a.m === b.m ? `${a.d}–${b.d} ${MONTHS[b.m - 1]}` : `${a.d} ${MONTHS[a.m - 1]} – ${b.d} ${MONTHS[b.m - 1]}`;
}

const newsWord = (n: number) => `${n} ${plural(n, ['новость', 'новости', 'новостей'])}`;

/** «Аналитики Альфа-Банка · 31.07.2026». */
function fullDate(iso: string | null | undefined): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}.${m[2]}.${m[1]}` : '';
}

export interface BankLine {
  text: string;
  caption: string;
  outdated: boolean;
  /** почему устарел: «банк ждал Urals $63, в новостях — $72» */
  note: string | null;
}

export function bankLine(b: BankView): BankLine {
  return {
    text: plain(b.text),
    // «Альфа-Банк» в подписи материала — это его аналитики: так подписано во всём интерфейсе.
    caption: [!b.publisher || b.publisher === 'Альфа-Банк' ? 'Аналитики Альфа-Банка' : b.publisher, fullDate(b.date)]
      .filter(Boolean)
      .join(' · '),
    outdated: b.outdated === true,
    note: b.outdated_note ?? null,
  };
}

// ─── «Главное за неделю» ────────────────────────────────────────────────────

export interface WeekRow {
  key: string;
  /** главное событие сюжета — карточка открывается по нему */
  eventId: string | null;
  level: Level;
  headline: string;
  dynamics: Dynamics;
  days: Day[];
  /** «22 новости за неделю · пик 23.10 — решение ЦБ» */
  countLine: string;
  why: string | null;
  /** «Что делать» из вывода — отдельной строкой */
  todo: string | null;
}

export interface WeekScreen {
  /** API собрал сводку за неделю; false — сервер ещё не умеет period=week и вернул ленту дня */
  available: boolean;
  /** «19–25 октября · 4 сюжета» */
  meta: string;
  rows: WeekRow[];
  bank: BankLine | null;
  action: { eventId: string; label: string } | null;
}

function countLineOf(story: Story, week: string[]): string {
  const head = `${newsWord(story.news_count)} за неделю`;
  let tail: string | null = null;
  if (story.peak) {
    // Пик о том же событии, что и заголовок сюжета, — без повтора заголовка.
    const bare = (t: string) => plain(t).replace(/…$/, '').trim().toLowerCase();
    const [a, b] = [bare(story.peak.what), bare(story.title)];
    const same = a.startsWith(b) || b.startsWith(a);
    tail = same ? `пик ${shortDate(story.peak.date)}` : `пик ${shortDate(story.peak.date)} — ${story.peak.what}`;
  }
  else if (story.dynamics === 'faded') {
    // Утих: «с 24.10 новых нет» — день после последней новости, если он внутри недели.
    const last = story.daily_counts.reduce((acc, n, i) => (n > 0 ? i : acc), -1);
    const sameDays = week.length === story.daily_counts.length;
    if (sameDays && last >= 0 && last < week.length - 1) tail = `с ${shortDate(week[last + 1])} новых нет`;
  }
  return [head, tail].filter(Boolean).join(' · ');
}

export function weekScreen(feed: Briefing, hidden: string[]): WeekScreen {
  const week = feed.week ?? [];
  const rows: WeekRow[] = (feed.stories ?? [])
    // Сюжет, все события которого пользователь скрыл, не показываем.
    .filter((st) => st.event_ids.length === 0 || st.event_ids.some((id) => !hidden.includes(id)))
    .map((st) => ({
      key: st.code,
      eventId:
        st.event_ids.find((id) => !hidden.includes(id)) ??
        (st.peak && !hidden.includes(st.peak.event_id) ? st.peak.event_id : null),
      level: st.level,
      headline: plain(st.title),
      dynamics: st.dynamics,
      days: daysOf(st.daily_counts, week),
      countLine: countLineOf(st, week),
      ...splitTodo(st.takeaway?.text ? plain(st.takeaway.text) : null),
    }));
  const meta = [periodText(week), rows.length > 0 ? `${rows.length} ${plural(rows.length, ['сюжет', 'сюжета', 'сюжетов'])}` : '']
    .filter(Boolean)
    .join(' · ');
  return {
    available: feed.period === 'week',
    meta,
    rows,
    bank: feed.bank ? bankLine(feed.bank) : null,
    // Действие недели открывает событие его темы; события нет ни в действии, ни в сюжете темы — кнопки нет.
    action: (() => {
      const a = feed.action;
      const eventId = a ? (a.event_id ?? rows.find((r) => r.key === a.code)?.eventId ?? null) : null;
      return a && eventId ? { eventId, label: a.label } : null;
    })(),
  };
}

// ─── «К чему уязвима компания» ──────────────────────────────────────────────

export const STRENGTH_LABEL: Record<RiskStrength, string> = { strong: 'Сильно', notable: 'Заметно', weak: 'Слабо' };
export const STRENGTH_FILLED: Record<RiskStrength, number> = { strong: 3, notable: 2, weak: 1 };

export interface RiskRow {
  code: string;
  label: string;
  strength: RiskStrength;
  estimate: boolean;
  why: string;
  now: { tag: string; text: string; eventId: string } | null;
  bank: BankLine | null;
  days: Day[];
  /** «53 новости» — ссылка на ленту с фильтром; null — новостей за неделю нет */
  newsLink: string | null;
}

export interface RiskScreen {
  /** «К чему уязвим холдинг» / «К чему уязвима компания» */
  title: string;
  rows: RiskRow[];
  limits: string[];
}

function riskRow(f: RiskFactor, week: string[]): RiskRow {
  const nowTail = [f.now?.publisher, shortDate(f.now?.date)].filter(Boolean).join(', ');
  return {
    code: f.code,
    label: f.label,
    strength: f.strength,
    estimate: f.is_estimate,
    why: plain(f.why),
    now: f.now ? { tag: f.now.direction, text: nowTail ? `${f.now.title} · ${nowTail}` : f.now.title, eventId: f.now.event_id } : null,
    bank: f.bank ? bankLine(f.bank) : null,
    days: daysOf(f.week_counts, week),
    newsLink: f.news_count > 0 ? newsWord(f.news_count) : null,
  };
}

/** Холдинг или компания — по подписи компании («Топливный оптовик, Москва (холдинг)»). */
export const isHolding = (companyName: string) => /холдинг/i.test(companyName);

/** Порядок факторов задаёт API под роль; здесь только перевод в строки экрана. */
export function riskScreen(map: RiskMap, companyName: string): RiskScreen {
  return {
    title: isHolding(companyName) ? 'К чему уязвим холдинг' : 'К чему уязвима компания',
    rows: map.factors.map((f) => riskRow(f, map.week)),
    limits: map.limits,
  };
}
