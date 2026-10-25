// Тесты главной «Новости» (версия A): брифинг из групп по фактору, вывод с уровнем, цепочка из данных, позиция банка
// только из разбора, запасной вид без новых полей API.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Briefing, CompanyExposure, FeedItem, Insight } from '../api/types.ts';
import { chainOf, levelOf, matchFeed, newsScreen, plain, whyOf, type NewsState } from './news.ts';

function item(id: string, score: number, codes: string[], extra: Partial<FeedItem> = {}): FeedItem {
  return {
    event_id: id,
    event: { title: `Событие ${id}`, date: '2026-10-23' },
    relevance: { score, reason: `причина ${id}` },
    has_bank_view: false,
    source: { id: `src:news:${id}`, kind: 'news', title: `Событие ${id}`, publisher: 'Коммерсантъ', url: null, published_at: '2026-10-23T13:30:00' },
    factors: codes.map((code) => ({ code, label: code })),
    channel: 'direct',
    channel_text: `событие в вашей отрасли: 45.31.1 Торговля оптовая деталями`,
    ...extra,
  } as FeedItem;
}

const feed: Briefing = {
  persona_id: 'p',
  summary: [],
  candidates: 500,
  items: [
    item('a', 0.65, ['rate'], { has_bank_view: true, short: 'Кредит у вас и у 11 компаний группы' }),
    item('b', 0.5, ['rate']),
    item('c', 0.46, ['fx'], { takeaway: { level: 'watch', text: '44 % платежей — импортёрам группы' } }),
    item('d', 0.2, ['consumer']),
    item('e', 0.4, []),
  ],
};

const exposure: CompanyExposure = {
  company_id: 'U',
  warnings: [],
  factors: [
    {
      code: 'rate',
      label: 'Стоимость заёмных денег',
      strength: 0.7,
      level: 'high',
      channel: null,
      estimate: false,
      evidence: [{ ref: 'g', label: 'Кредиты у компаний группы', value: '11 из 28' }],
    },
  ],
};

const base: NewsState = { feed, exposure, hidden: [], filter: null, showAll: false, lead: null, today: '2026-10-24' };

test('главное за день — три темы с уровнем; лента — по одному событию на тему, первые четыре', () => {
  const s = newsScreen(base);
  assert.deepEqual(
    s.day.map((d) => [d.eventId, d.level, d.headline, d.todo]),
    [
      ['a', 'act', 'Событие a', null],
      ['c', 'watch', 'Событие c', null],
      ['e', 'watch', 'Событие e', null],
    ],
  );
  // События из «Главного за день» второй раз в ленте не показываем.
  assert.deepEqual(
    s.events.map((e) => e.eventId),
    ['d'],
  );
  assert.equal(s.day[0].fromModel, false);
  assert.equal(s.more, 0);
  assert.equal(s.updated, '24 октября · последняя новость — 23.10, 13:30');
  assert.deepEqual(s.action, { eventId: 'a', topic: 'структуру долга', label: 'Обсудить структуру долга с менеджером' });
  assert.equal(s.bank, null);
});

test('вывод: takeaway → short → строка без кодов ОКВЭД; уровень — из takeaway или значимости', () => {
  assert.equal(whyOf(feed.items[2]), '44 % платежей — импортёрам группы');
  assert.equal(whyOf(feed.items[0]), 'Кредит у вас и у 11 компаний группы');
  assert.equal(whyOf(feed.items[1]), 'Событие в вашей отрасли');
  assert.equal(levelOf(feed.items[0]), 'act');
  assert.equal(levelOf(feed.items[2]), 'watch');
  assert.equal(levelOf(feed.items[3]), 'info');
});

test('цепочка — из данных компании, без выдуманных узлов', () => {
  assert.deepEqual(chainOf([feed.items[0]], exposure), ['Ставка', 'Стоимость заёмных денег', 'Кредиты у компаний группы · 11 из 28', 'Вы']);
  assert.deepEqual(chainOf([feed.items[4]], null), ['Своя отрасль', 'Вы']);
});

test('фильтр по теме и «показать ещё»', () => {
  const many = { ...feed, items: [...feed.items, item('f', 0.25, ['labor']), item('g', 0.22, ['gov'])] };
  const s = newsScreen({ ...base, feed: many });
  assert.deepEqual(
    s.events.map((e) => e.eventId),
    ['f', 'g', 'd'],
  );
  assert.equal(s.more, 0);
  const lots = { ...feed, items: [...many.items, item('h', 0.21, ['fx2']), item('i', 0.2, ['oil'])] };
  assert.equal(newsScreen({ ...base, feed: lots }).more, 1);
  assert.equal(newsScreen({ ...base, feed: lots, showAll: true }).more, 0);
  const f = newsScreen({ ...base, filter: 'rate' });
  assert.deepEqual(
    f.events.map((e) => e.eventId),
    ['a', 'b'],
  );
  assert.equal(f.chips.find((c) => c.key === 'rate')?.selected, true);
});

const lead = {
  id: 'ins:a',
  event: { title: 'ЦБ сохранил ставку', date: '2026-10-23' },
  relevance: { score: 0.65, reason: 'r' },
  what_happened: [{ origin: 'fact', text: 'Банк России сохранил ставку 14 %.', refs: [] }],
  why_it_matters: [
    { origin: 'data', text: 'Кредиты у 11 из 28 компаний группы.', refs: [] },
    { origin: 'ai', text: 'Долг не подешевеет до конца 2026.', refs: [], confidence: 'high' },
  ],
  consequences: { risks: [], opportunities: [], factors: [] },
  bank_view: [{ origin: 'bank', text: 'Банк ждёт 14 % до конца года', refs: ['src:alfa:k#p1'] }],
  actions: [{ text: 'Уточнить долю плавающих кредитов', kind: 'question', refs: [] }],
  sources: [
    { id: 'src:alfa:k#p1', kind: 'alfa_analytics', title: 'Ключевая ставка', publisher: 'Альфа-Банк', url: null, published_at: '2026-09-11', page: 1, fragment: 'ожидаем 14,0 %' },
  ],
  features_used: [],
  quality: { checks_passed: [], warnings: [] },
  bank_position: { statement: 'Альфа-Банк ожидает ставку 14 % до конца 2026 года' },
} as unknown as Insight;

test('с разбором главного события: вывод, «что делать» и позиция банка с подписью аналитиков', () => {
  const s = newsScreen({ ...base, lead });
  assert.deepEqual(s.day[0], {
    eventId: 'a',
    level: 'act',
    headline: 'Долг не подешевеет до конца 2026.',
    fromModel: true,
    why: 'Кредит у вас и у 11 компаний группы',
    todo: 'Уточнить долю плавающих кредитов',
  });
  assert.deepEqual(s.bank, {
    statement: 'Альфа-Банк ожидает ставку 14 % до конца 2026 года',
    caption: 'Аналитики Альфа-Банка · «Ключевая ставка» · 11.09.2026 · стр. 1',
    eventId: 'a',
  });
  // В ленте главное событие — только при выборе его темы, с позицией банка.
  const byTopic = newsScreen({ ...base, lead, filter: 'rate' });
  assert.equal(byTopic.events[0].bank, 'Альфа-Банк ожидает ставку 14 % до конца 2026 года');
  assert.equal(byTopic.events[1].bank, null);
  assert.equal(s.leadInsight?.id, 'ins:a');
});

test('скрытое не попадает на экран; пустая лента — пустой экран', () => {
  const s = newsScreen({ ...base, hidden: ['a'] });
  assert.equal(s.day[0].eventId, 'b');
  assert.equal(newsScreen({ ...base, feed: { ...feed, items: [] } }).empty, true);
});

test('поиск по ленте: все слова запроса, с учётом окончаний', () => {
  const items = [
    item('a', 0.6, ['rate'], { event: { title: 'Банк России сохранил ключевую ставку', date: '2026-10-23' } }),
    item('b', 0.5, ['fx'], { event: { title: 'Курс доллара опустился', date: '2026-10-23' } }),
  ];
  assert.deepEqual(
    matchFeed(items, 'ключевой ставки').map((i) => i.event_id),
    ['a'],
  );
  assert.deepEqual(
    matchFeed(items, 'коммерсантъ').map((i) => i.event_id),
    ['a', 'b'],
  );
  assert.deepEqual(matchFeed(items, ' '), []);
});

test('без технических оборотов для руководителя', () => {
  assert.equal(plain('По карте чувствительности у компании есть кредит в банке'), 'У компании есть кредит в банке');
  assert.equal(plain('Сила связи по карте чувствительности высокая'), 'Сила связи высокая');
  assert.equal(plain('Связь видна по данным из карты чувствительности'), 'Связь видна по данным из данных банка о компании');
  assert.equal(plain('Сверено с картой чувствительности'), 'Сверено с данными банка о компании');
  assert.equal(chainOf([item('x', 0.5, ['fx'])], { company_id: 'U', warnings: [], factors: [{ code: 'fx', label: 'Курс валют', strength: 0.6, level: 'high', channel: null, estimate: false, evidence: [] }] }).join(' → '), 'Курс валют → Вы');
});

test('ход разбора: живые шаги из API, иначе пройденные этапы и текущий', async () => {
  const { stepsOf } = await import('./steps.ts');
  const job = { insight_id: 'i', event_id: 'e', status: 'running', stage: 'Ищу аналитику банка', stages_done: ['Смотрю данные компании'], elapsed_s: 3, eta_s: 40, queue_position: null, error: null, trace_id: null } as const;
  assert.deepEqual(
    stepsOf({ ...job }).map((s) => [s.title, s.state]),
    [
      ['Смотрю данные компании', 'done'],
      ['Ищу аналитику банка', 'running'],
    ],
  );
  assert.equal(stepsOf({ ...job, steps: [{ title: 'Нашёл 3 материала', state: 'done', found: ['ЦБ'] }] })[0].title, 'Нашёл 3 материала');
  assert.equal(stepsOf({ ...job, status: 'queued', queue_position: 3 }).at(-1)?.title, 'Жду очереди: передо мной 2');
  assert.equal(stepsOf({ ...job, status: 'queued', queue_position: 1 }).at(-1)?.title, 'Жду очереди');
  assert.equal(stepsOf(null)[0].state, 'running');
});

test('подсветка цитат в полном тексте', async () => {
  const { highlight } = await import('./highlight.ts');
  const segs = highlight('ЦБ сохранил ставку 14%. Инфляционные ожидания остаются высокими.', ['инфляционные ожидания остаются', 'коротко']);
  assert.deepEqual(segs, [
    { text: 'ЦБ сохранил ставку 14%. ', mark: false },
    { text: 'Инфляционные ожидания остаются', mark: true },
    { text: ' высокими.', mark: false },
  ]);
  assert.deepEqual(highlight('текст', []), [{ text: 'текст', mark: false }]);
});

test('фильтр по теме, которой нет, не действует; «главное за день» пустое, если всё слабое', () => {
  const s = newsScreen({ ...base, filter: 'oil' });
  assert.equal(s.chips[0].selected, true);
  assert.equal(s.events.length, 1);
  const weak = newsScreen({ ...base, feed: { ...feed, items: [item('w', 0.2, ['rate'])] } });
  assert.deepEqual(weak.day, []);
  assert.equal(weak.events.length, 1);
});
