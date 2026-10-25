// «Как получен вывод»: человеческое резюме трассы агента — что проверено, что нашлось, чего нет, чем кончилась
// самопроверка. Техника (модели, токены, имена инструментов) остаётся в свёрнутом блоке «Для проверки».
// Только то, что есть в шагах трассы: ничего не досчитываем и не додумываем.
import type { Trace, TraceStep } from '../api/types.ts';
import { plural } from './screens.ts';

export interface TraceStory {
  /** что агент сделал и что нашёл */
  done: string[];
  /** чего не нашлось или не удалось построить */
  missing: string[];
  check: {
    /** самопроверка вообще была */
    ran: boolean;
    passed: boolean;
    /** одной фразой: что проверяли и чем кончилось */
    text: string;
    /** какие замечания были — человеческими словами */
    issues: string[];
  };
}

// Служебный id компании — номер из трёх и больше цифр: «Компания №92457», «U_4909». Короткие номера — это места
// в рейтинге («компании №1 по выручке»), их не трогаем.
const ID = String.raw`(?:[Кк]омпани[яиюейям]{0,2}\s*№\s*\d{3,}|U_\d{3,})`;
const ID_DOT = new RegExp(String.raw`${ID}\s*·\s*`, 'g');
const ID_LIST = new RegExp(String.raw`${ID}(?:(?:,\s*|\s+и\s+)${ID})+`, 'g');
const ID_ONE = new RegExp(ID, 'g');

/** Убрать служебные id из человеческого текста: «Компания №92457» → «Компания», «U_4909» → «компания». */
export function scrubIds(text: string): string {
  if (!/\s/.test(text) || !/№|U_/.test(text)) return text; // одно слово — идентификатор, его не трогаем
  return (
    text
      // в перечислениях «U_4754 · поставщик · 14 % оборота» id — просто метка строки: убираем вместе с точкой
      .replace(ID_DOT, '')
      // список из нескольких: «Компания №4754, Компания №153112 и Компания №17010» → «3 компании»
      .replace(ID_LIST, (m) => {
        const n = (m.match(ID_ONE) ?? []).length;
        return `${n} ${plural(n, ['компания', 'компании', 'компаний'])}`;
      })
      // одиночный: падеж слова сохраняем, номер убираем; голый id — «компания», с заглавной в начале фразы
      .replace(ID_ONE, (m, offset: number, all: string) => {
        const word = m.match(/^[Кк]омпани[яиюейям]{0,2}/)?.[0];
        if (word) return word;
        return offset === 0 || /[.!?]\s*$/.test(all.slice(0, offset)) ? 'Компания' : 'компания';
      })
      .replace(/[ \t]{2,}/g, ' ')
  );
}

const ABBR: [RegExp, string][] = [
  // не трогаем слово перед дефисом: «ВЭД-контракты»
  [/(?<![А-ЯЁа-яё])ВЭД(?![А-ЯЁа-яё-])/, 'ВЭД (внешнеэкономическая деятельность)'],
  [/(?<![А-ЯЁа-яё])ФОТ(?![А-ЯЁа-яё-])/, 'ФОТ (фонд оплаты труда)'],
];

/** Сокращения, которых руководитель может не знать: расшифровка при первом упоминании, «п.п.» — словами. */
export function expandAbbr(text: string): string {
  if (!/\s/.test(text) || !/ВЭД|ФОТ|п\.\s?п\./.test(text)) return text;
  let out = text.replace(/(\d+(?:[,.]\d+)?)\s*п\.\s?п\./g, (m: string, n: string, offset: number, all: string) => {
    const fraction = /[,.]/.test(n);
    const words = fraction ? 'процентного пункта' : plural(Number(n), ['процентный пункт', 'процентных пункта', 'процентных пунктов']);
    // точка «п.п.» была и концом предложения — возвращаем её
    const rest = all.slice(offset + m.length);
    return `${n} ${words}${/^\s*$/.test(rest) || /^\s+[А-ЯЁA-Z]/.test(rest) ? '.' : ''}`;
  });
  for (const [re, full] of ABBR) if (!out.includes(full)) out = out.replace(re, full);
  return out;
}

/** Где текст — дословная цитата или текст новости: его не меняем, даже если в нём есть «№». */
const VERBATIM = new Set(['quote', 'quotes', 'fragment', 'full_text', 'title']);

/** Пройти по ответу API и убрать служебные id из всех строк с текстом. */
export function scrubDeep<T>(value: T): T {
  if (typeof value === 'string') return expandAbbr(scrubIds(value)) as T;
  if (Array.isArray(value)) return value.map(scrubDeep) as T;
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, VERBATIM.has(k) ? v : scrubDeep(v)]),
    ) as T;
  }
  return value;
}

/** Замечания самопроверки → понятные слова. Неизвестные формулировки не показываем: их видно в «Для проверки». */
const ISSUES: [RegExp, string][] = [
  [/суммы в рублях пишет только расчётный инструмент/i, 'суммы в рублях без расчёта по формуле'],
  [/чисел нет в данных о компании/i, 'числа, которых нет в данных о компании'],
  [/вывод вынеси отдельным|вывод \(«поэтому/i, 'вывод модели, записанный как данные о компании'],
  [/нет данных о компании/i, 'в «почему важно» не было данных о компании'],
  [/цитат|не найдена в источнике/i, 'цитата, которой нет в источнике'],
  [/дат[аы]|прошедш/i, 'устаревшая дата'],
];

const tool = (s: TraceStep, name: string | RegExp) => s.kind === 'tool' && !!s.tool && (typeof name === 'string' ? s.tool === name : name.test(s.tool));

export function traceStory(trace: Trace): TraceStory {
  const steps = trace.steps;
  const done: string[] = [];
  const missing: string[] = [];

  const profile = steps.filter((s) => tool(s, /^get_(profile|exposure_map)$/));
  if (profile.length > 0) {
    const features = new Set(profile.flatMap((s) => s.output_refs ?? []).filter((r) => r.startsWith('feat:')));
    done.push(
      features.size > 0
        ? `Посмотрел данные банка о компании: ${features.size} ${plural(features.size, ['признак', 'признака', 'признаков'])}`
        : 'Посмотрел данные банка о компании',
    );
  }
  if (steps.some((s) => tool(s, 'get_group_impact'))) done.push('Посчитал, каких компаний группы касается событие');

  for (const s of steps.filter((x) => tool(x, 'get_counterparty_chain'))) {
    const why = s.summary?.match(/^каналов нет:\s*(.+)$/i)?.[1];
    if (why) missing.push(`Цепочку через покупателей и поставщиков не построил: ${why}`);
    else if (/ошибк|не удалось/i.test(s.summary ?? '')) missing.push('Цепочку через покупателей и поставщиков построить не удалось');
    else done.push('Проверил, дойдёт ли событие через покупателей и поставщиков');
  }

  const searches = steps.filter((s) => tool(s, 'search_alfa_analytics'));
  if (searches.length > 0) {
    const materials = new Set(searches.flatMap((s) => s.output_refs ?? []).map((r) => r.split('#')[0]));
    const pages = new Set(steps.filter((s) => tool(s, 'alfa_page_text')).flatMap((s) => s.output_refs ?? [])).size;
    if (materials.size > 0)
      done.push(
        `Нашёл материалы аналитиков Альфа-Банка: ${materials.size}` +
          (pages > 0 ? `, прочитал ${pages} ${plural(pages, ['страницу', 'страницы', 'страниц'])}` : ''),
      );
    else missing.push('Материалов Альфа-Банка по теме не нашёл');
  }

  const news = steps.filter((s) => tool(s, 'search_news'));
  if (news.length > 0) {
    const found = new Set(news.flatMap((s) => s.output_refs ?? [])).size;
    if (found > 0) done.push(`Нашёл другие новости по теме: ${found}`);
    else missing.push('Других новостей по теме не нашёл');
  }

  if (steps.some((s) => tool(s, /^estimate_/))) done.push('Посчитал влияние в рублях по формуле с допущениями');
  if (steps.some((s) => tool(s, 'get_products_for_risk'))) done.push('Подобрал продукты банка под этот риск');

  // Самопроверка: замечания по кругам, исправления, что осталось в итоге и что убрано из разбора.
  const checks = steps.filter((s) => s.kind === 'check' && s.verdict);
  const retries = steps.filter((s) => s.kind === 'retry').length;
  const labels = (list: TraceStep[]) => [
    ...new Set(list.flatMap((s) => ISSUES.filter(([re]) => re.test(s.summary ?? '')).map(([, label]) => label))),
  ];
  // Итог — по последней содержательной проверке: служебная (предупреждения о данных) идёт после неё и не в счёт.
  const last = [...checks].reverse().find((s) => !/служебные предупреждения/i.test(s.summary ?? ''));
  const passed = checks.length > 0 && (last ? last.verdict === 'pass' : true);
  const removed = Number(last?.summary?.match(/убрано\s+(\d+)/)?.[1] ?? 0);
  const left = last && last.verdict === 'fail' ? labels([last]) : [];
  const issues = labels(checks.filter((s) => s.verdict === 'fail'));
  let text: string;
  if (checks.length === 0) text = 'Самопроверка не выполнялась.';
  else if (issues.length === 0 && checks.every((s) => s.verdict === 'pass'))
    text = 'Самопроверка пройдена: числа и выводы сверены с данными о компании и источниками.';
  else {
    const fixes = retries > 0 ? ` Модель исправляла ответ ${retries} ${plural(retries, ['раз', 'раза', 'раз'])}.` : '';
    text = passed
      ? `Самопроверка нашла замечания и после исправления пройдена.${fixes}`
      : `Итоговая самопроверка не пройдена.${fixes}` +
        (left.length > 0 ? ` Осталось: ${left.join('; ')}.` : '') +
        (removed > 0 ? ` Такие места убраны из разбора: ${removed}.` : '');
  }

  return { done: [...new Set(done)], missing: [...new Set(missing)], check: { ran: checks.length > 0, passed, text, issues } };
}
