// Тесты «Главного за неделю» (B1) и «К чему уязвима компания» (B2, B3): сюжеты, динамика, пик и «новых нет»,
// честный вид, когда сервер сводку недели не собрал, пометки «Оценка» и «прогноз устарел», ограничения карты.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Briefing, FeedItem, RiskMap, Story } from '../api/types.ts';
import { newsScreen } from './news.ts';
import { daysLabel, daysOf, periodText, riskScreen, splitTodo, weekScreen } from './week.ts';

const WEEK = ['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24', '2026-10-25'];

function story(code: string, extra: Partial<Story> = {}): Story {
  return {
    code,
    title: `Сюжет ${code}`,
    level: 'watch',
    dynamics: 'grew',
    daily_counts: [0, 0, 1, 2, 9, 0, 0],
    news_count: 12,
    event_ids: [`e-${code}`],
    ...extra,
  };
}

const week: Briefing = {
  persona_id: 'p',
  summary: [],
  items: [],
  period: 'week',
  week: WEEK,
  stories: [
    story('rate', {
      level: 'act',
      news_count: 22,
      peak: { date: '2026-10-23', what: 'решение ЦБ', event_id: 'e-cb' },
      takeaway: { level: 'act', text: 'по карте чувствительности 178 из 368 компаний группы зависят от кредитов' },
    }),
    story('fx', { level: 'info', dynamics: 'faded', daily_counts: [0, 3, 3, 1, 0, 0, 0], news_count: 7 }),
  ],
  bank: { text: 'Альфа-Банк ожидает ставку 14,0 % до конца 2026 года', publisher: 'Альфа-Банк', date: '2026-09-11', outdated: false },
  action: { code: 'rate', topic: 'долг', label: 'Обсудить долг с менеджером', event_id: null },
};

test('неделя: период, число сюжетов, пик, «новых нет», вывод без служебных слов', () => {
  const s = weekScreen(week, []);
  assert.equal(s.available, true);
  assert.equal(s.meta, '19–25 октября · 2 сюжета');
  const [rate, fx] = s.rows;
  assert.equal(rate.countLine, '22 новости за неделю · пик 23.10 — решение ЦБ');
  assert.equal(rate.why, '178 из 368 компаний группы зависят от кредитов');
  assert.equal(rate.eventId, 'e-rate');
  // Последняя новость в четверг 22.10 — значит, с пятницы новых нет.
  assert.equal(fx.countLine, '7 новостей за неделю · с 23.10 новых нет');
  assert.equal(fx.why, null);
  assert.deepEqual(splitTodo('Ставка продержится дольше. Что делать: сверьте сроки пересмотра ставок.'), {
    why: 'Ставка продержится дольше.',
    todo: 'сверьте сроки пересмотра ставок.',
  });
  assert.deepEqual(splitTodo('Без действия'), { why: 'Без действия', todo: null });
  const cut = weekScreen(
    { ...week, stories: [story('oil', { title: 'ЦБ повысил прогноз цены на нефть Urals до $72 за…', peak: { date: '2026-10-24', what: 'ЦБ повысил прогноз цены на нефть Urals до $72 за баррель', event_id: 'e' } })] },
    [],
  );
  assert.equal(cut.rows[0].countLine, '12 новостей за неделю · пик 24.10');
  const same = weekScreen({ ...week, stories: [story('rate', { title: 'ЦБ не спешит', peak: { date: '2026-10-23', what: 'ЦБ не спешит', event_id: 'e' } })] }, []);
  assert.equal(same.rows[0].countLine, '12 новостей за неделю · пик 23.10');
  assert.deepEqual(s.bank, { text: week.bank!.text, caption: 'Аналитики Альфа-Банка · 11.09.2026', outdated: false, note: null });
  // У действия нет события — открываем главное событие сюжета его темы; темы среди сюжетов нет — кнопки нет.
  assert.deepEqual(s.action, { eventId: 'e-rate', label: 'Обсудить долг с менеджером' });
  assert.equal(weekScreen({ ...week, action: { ...week.action!, code: 'oil' } }, []).action, null);
});

test('неделя: сюжет со всеми скрытыми событиями не показываем; сервер без period=week — сводки нет', () => {
  const s = weekScreen(week, ['e-rate']);
  assert.deepEqual(
    s.rows.map((r) => r.key),
    ['fx'],
  );
  const day: Briefing = { persona_id: 'p', summary: [], items: [{ event_id: 'x' } as FeedItem], period: 'day' };
  const d = weekScreen(day, []);
  assert.equal(d.available, false);
  assert.deepEqual(d.rows, []);
  assert.equal(d.meta, '');
});

test('дни графика по датам из API и подпись для экранного диктора', () => {
  const days = daysOf([0, 2], ['2026-10-19', '2026-10-20']);
  assert.deepEqual(
    days.map((d) => d.letter),
    ['П', 'В'],
  );
  assert.equal(daysLabel(days), 'Новостей по дням: понедельник 19.10 — 0, вторник 20.10 — 2');
  assert.equal(daysOf([1], [])[0].name, 'день 1');
  assert.equal(periodText(['2026-09-28', '2026-10-04']), '28 сентября – 4 октября');
  assert.equal(periodText([]), '');
});

const map: RiskMap = {
  company_id: 'U',
  role: 'owner',
  week: WEEK,
  limits: ['Не оцениваем спрос покупателей и поставщиков: платежи в выгрузке покрывают 0,7 % выручки.'],
  factors: [
    {
      code: 'commodity_oil',
      label: 'Нефть и топливо',
      strength: 'strong',
      why: 'Ваша отрасль — оптовая торговля топливом',
      is_estimate: false,
      now: { event_id: 'e1', title: 'Brent выше $115', direction: 'Дорожает', publisher: 'Коммерсантъ', date: '2026-10-23' },
      bank: { text: 'Банк ждал Urals $63 в 2026 году', publisher: 'Аналитики Альфа-Банка', date: '2026-07-31', outdated: true, outdated_note: 'в новостях — $72' },
      week_counts: [0, 0, 9, 11, 10, 11, 12],
      news_count: 53,
    },
    { code: 'fx', label: 'Курс рубля', strength: 'notable', why: '', is_estimate: true, now: null, bank: null, week_counts: [0, 0, 0, 0, 0, 0, 0], news_count: 0 },
  ],
};

test('карта: строки, пометки, подписи банка и ссылки на новости', () => {
  const s = riskScreen(map, 'Топливный оптовик, Москва (холдинг)');
  assert.equal(s.title, 'К чему уязвим холдинг');
  const [oil, fx] = s.rows;
  assert.deepEqual(oil.now, { tag: 'Дорожает', text: 'Brent выше $115 · Коммерсантъ, 23.10', eventId: 'e1' });
  assert.deepEqual(oil.bank, {
    text: 'Банк ждал Urals $63 в 2026 году',
    caption: 'Аналитики Альфа-Банка · 31.07.2026',
    outdated: true,
    note: 'в новостях — $72',
  });
  assert.equal(oil.newsLink, '53 новости');
  assert.equal(oil.days[6].letter, 'В');
  assert.equal(fx.estimate, true);
  assert.equal(fx.bank, null);
  assert.equal(fx.now, null);
  assert.equal(fx.newsLink, null);
  assert.equal(riskScreen(map, 'Оптовик автозапчастей, Москва').title, 'К чему уязвима компания');
  assert.deepEqual(s.limits, map.limits);
});

function item(id: string, score: number, codes: string[]): FeedItem {
  return {
    event_id: id,
    event: { title: `Событие ${id}`, date: '2026-10-23' },
    relevance: { score, reason: `причина ${id}` },
    has_bank_view: false,
    source: { id: `src:news:${id}`, kind: 'news', title: `Событие ${id}`, publisher: 'Коммерсантъ', url: null, published_at: '2026-10-23T13:30:00' },
    factors: codes.map((code) => ({ code, label: code })),
    channel: 'direct',
    channel_text: 'событие в вашей отрасли',
  } as FeedItem;
}

test('лента: фильтр по фактору с карты находит и неглавный фактор события', () => {
  const feed: Briefing = { persona_id: 'p', summary: [], items: [item('x', 0.6, ['rate', 'fx']), item('y', 0.5, ['oil'])] };
  const s = newsScreen({ feed, exposure: null, hidden: [], filter: 'fx', showAll: false, lead: null, today: '2026-10-25' });
  assert.deepEqual(
    s.events.map((e) => e.eventId),
    ['x'],
  );
  assert.equal(s.chips.find((c) => c.selected)?.key, 'fx');
  assert.equal(s.chips.find((c) => c.key === 'rate')?.count, 1);
  // «Своя отрасль» — события без факторов.
  const own = newsScreen({ feed: { ...feed, items: [...feed.items, item('z', 0.4, [])] }, exposure: null, hidden: [], filter: 'industry', showAll: false, lead: null, today: '2026-10-25' });
  assert.deepEqual(
    own.events.map((e) => e.eventId),
    ['z'],
  );
});
