// Тесты селекторов экранов: одинаковое состояние → одинаковая модель; смена роли, скрытие, фильтр и статус
// данных меняют экран предсказуемо. Запуск: npm test (node --test без сборки).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Briefing, CompanyExposure, FeedItem, Insight, Statement } from '../api/types.ts';
import { cardScreen, direction, eventValue, feedScreen, humanize, leadingNumber, plural, sourceMark, type FeedState } from './screens.ts';

function item(id: string, score: number, codes: string[], extra: Partial<FeedItem> = {}): FeedItem {
  return {
    event_id: id,
    event: { title: `Событие ${id}`, date: '2026-10-23' },
    relevance: { score, reason: `причина ${id}` },
    has_bank_view: true,
    source: { id: `src:news:${id}`, kind: 'news', title: `Событие ${id}`, publisher: 'Коммерсантъ', url: null, published_at: '2026-10-23T13:30:00' },
    factors: codes.map((code) => ({ code, label: code })),
    channel: 'direct',
    channel_text: `для вас по ${codes[0] ?? 'отрасли'}`,
    ...extra,
  } as FeedItem;
}

const feed: Briefing = {
  persona_id: 'p-u8318-cfo',
  summary: [],
  items: [
    item('a', 0.65, ['rate']),
    item('b', 0.5, ['rate']),
    item('c', 0.46, ['fx']),
    item('d', 0.2, ['consumer']),
    item('e', 0.4, []),
  ],
};

const exposure: CompanyExposure = {
  company_id: 'U_8318',
  warnings: [],
  factors: [
    { code: 'rate', label: 'Стоимость заёмных денег', strength: 0.7, level: 'high', channel: null, estimate: false, evidence: [{ ref: 'feat:LOAN', label: 'Кредиты в банке', value: 'да' }, { ref: 'group', label: 'Кредиты у компаний группы', value: '11 из 28' }] },
    { code: 'fx', label: 'Курс рубля', strength: 0.65, level: 'high', channel: null, estimate: false, evidence: [{ ref: 'payments', label: 'Платежи группе с ВЭД', value: '44 % всех платежей компании; U_1 — 7,3 млрд ₽' }] },
    { code: 'consumer', label: 'Спрос', strength: 0.4, level: 'medium', channel: null, estimate: false, evidence: [] },
  ],
};

const base: FeedState = { feed, exposure, role: 'cfo', hidden: [], filter: null, lastVisit: '2026-10-22', showAll: false };

test('лента группирует по фактору, одна фраза «для вас» на группу', () => {
  const s = feedScreen(base);
  assert.deepEqual(
    s.groups.map((g) => g.key),
    ['rate', 'fx', 'industry'],
  );
  const rate = s.groups[0];
  assert.equal(rate.headlines.length, 2);
  assert.equal(rate.forYou, 'для вас по rate');
  assert.equal(rate.caps, 'Ставка · 2 материала · 23.10');
  assert.equal(rate.isNew, true);
});

test('события ниже 0,3 свёрнуты, «Показать» их разворачивает', () => {
  const s = feedScreen(base);
  assert.deepEqual(s.collapsed, { count: 1, titles: ['Событие d'], expanded: false });
  const all = feedScreen({ ...base, showAll: true });
  assert.equal(all.collapsed?.expanded, true);
  assert.ok(all.groups.some((g) => g.key === 'consumer'));
});

test('заголовок сводки считает события и те, что требуют решения', () => {
  assert.equal(feedScreen(base).headline, 'С 22 октября для вас: 5 событий, 1 требует решения');
  assert.equal(feedScreen({ ...base, lastVisit: null }).headline, 'Для вас: 5 событий, 1 требует решения');
  assert.deepEqual(feedScreen(base).mainAction, { eventId: 'a', topic: 'структуру долга', label: 'Обсудить с менеджером структуру долга' });
});

test('верх экрана зависит от роли: финансистам — показатели, собственнику — брифинг', () => {
  const cfo = feedScreen(base).top;
  assert.equal(cfo?.kind, 'indicators');
  if (cfo?.kind === 'indicators') {
    assert.deepEqual(
      cfo.items.map((i) => [i.code, i.value]),
      [
        ['rate', '11 из 28'],
        ['fx', '44 %'],
        ['consumer', 'средняя связь'],
      ],
    );
  }
  const owner = feedScreen({ ...base, role: 'owner' }).top;
  assert.equal(owner?.kind, 'brief');
  if (owner?.kind === 'brief') assert.equal(owner.points.length, 3);
});

test('скрытое пропадает из ленты и из счётчиков, фильтр оставляет одну группу', () => {
  const s = feedScreen({ ...base, hidden: ['a', 'b'] });
  assert.equal(s.hiddenCount, 2);
  assert.ok(!s.groups.some((g) => g.key === 'rate'));
  assert.equal(s.chips[0].count, 3);
  const f = feedScreen({ ...base, filter: 'fx' });
  assert.deepEqual(
    f.groups.map((g) => g.key),
    ['fx'],
  );
  assert.equal(f.chips.find((c) => c.key === 'fx')?.selected, true);
});

test('одна фраза «для вас» не повторяется у разных групп', () => {
  const same = { ...feed, items: [item('a', 0.65, ['rate'], { channel_text: 'своя отрасль' }), item('c', 0.5, ['fx'], { channel_text: 'своя отрасль' })] };
  const fx = { ...exposure.factors[1], channel: { kind: 'group' as const, text: 'через импортёров группы' } };
  const s = feedScreen({ ...base, feed: same, exposure: { ...exposure, factors: [exposure.factors[0], fx] } });
  assert.deepEqual(
    s.groups.map((g) => g.forYou),
    ['своя отрасль', 'через импортёров группы'],
  );
});

test('пустая лента — пустой экран без верхнего блока брифинга', () => {
  const s = feedScreen({ ...base, feed: { ...feed, items: [] }, role: 'owner' });
  assert.equal(s.empty, true);
  assert.equal(s.top, null);
});

test('сворачиваются события ниже 0,3, а не группы целиком', () => {
  const mixed = { ...feed, items: [item('a', 0.65, ['rate']), item('z', 0.2, ['rate'])] };
  const s = feedScreen({ ...base, feed: mixed });
  assert.deepEqual(
    s.groups[0].headlines.map((h) => h.eventId),
    ['a'],
  );
  assert.equal(s.collapsed?.count, 1);
});

test('строка «для вас» без кодов ОКВЭД и служебных пометок', () => {
  assert.equal(
    humanize('событие в вашей отрасли: 45.31.1 Торговля оптовая автомобильными деталями, узлами и принадлежностями, кроме деятельности агентов'),
    'событие в вашей отрасли',
  );
  assert.equal(humanize('через поставщиков с ВЭД — оценка по отрасли'), 'через поставщиков с ВЭД');
  assert.equal(
    humanize('через группу с ВЭД: 44 % всех платежей идут 3 компаниям группы; что они импортируют — оценка по отрасли'),
    'через группу с ВЭД: 44 % всех платежей идут 3 компаниям группы',
  );
  assert.equal(humanize('Компании группы с ОКВЭД 45.1, 45.2, 45.32, 47, 56'), 'Компании группы');
  assert.equal(humanize('кредит 50 млн ₽; ставка плавающая'), 'кредит 50 млн ₽; ставка плавающая');
  assert.equal(humanize('44 % всех платежей идут 3 компаниям группы'), '44 % всех платежей идут 3 компаниям группы');
});

test('значение и направление события — из заголовков', () => {
  assert.equal(eventValue(['Банк России принял решение сохранить ключевую ставку на уровне 14,00% годовых'], 'rate'), '14,00 %');
  assert.equal(eventValue(['Курс доллара. Прогноз', 'Курс доллара на Forex опустился ниже 81 рубля'], 'fx'), '81 ₽');
  assert.equal(eventValue(['Выдачи кредитов снизились на 71%'], 'fx'), null);
  assert.equal(eventValue(['ЦБ повысил прогноз цены на нефть Urals до $72 за баррель'], 'commodity_oil_gas'), '$72');
  assert.equal(eventValue(['Минпромторг предложил утильсбор'], 'tax_regulation'), null);
  assert.equal(eventValue(['ЦБ снизил ставку с 17% до 16,5%'], 'rate'), '16,5 %');
  assert.equal(eventValue(['Доллар подешевел на 1,5 рубля, до 80 рублей'], 'fx'), '80 ₽');
  assert.equal(eventValue(['В 2025 15% компаний'], 'rate'), '15 %');
  assert.equal(direction('ЦБ не снизил ставку'), 'держится');
  assert.equal(direction('Рубль ослаб до 85 рублей за доллар', 'fx'), 'растёт');
  assert.equal(direction('Банк России сохранил ставку'), 'держится');
  assert.equal(direction('Курс опустился ниже 81 рубля'), 'снижается');
});

test('позиция банка и фраза «для вас» — из уже собранного разбора', () => {
  const s = feedScreen({ ...base, insights: { a: insight } });
  const rate = s.groups[0];
  assert.equal(rate.forYou, 'Долг не подешевеет до конца 2026.');
  assert.equal(rate.bank?.text, 'Банк ждёт 14 % до конца года');
  assert.equal(s.bankOfDay?.eventId, 'a');
  assert.equal(feedScreen({ ...base, insights: { c: { ...insight } } }).bankOfDay, null);
  assert.equal(feedScreen(base).bankOfDay, null);
});

test('монограммы источников вместо логотипов', () => {
  assert.equal(sourceMark({ kind: 'news', publisher: 'Банк России' }), 'ЦБ');
  assert.equal(sourceMark({ kind: 'news', publisher: 'Коммерсантъ' }), 'Ъ');
  assert.equal(sourceMark({ kind: 'news', publisher: 'Новые известия' }), 'НИ');
  assert.equal(sourceMark({ kind: 'alfa_analytics', publisher: 'Альфа-Банк' }), null);
  assert.equal(plural(21, ['событие', 'события', 'событий']), 'событие');
  assert.equal(plural(12, ['событие', 'события', 'событий']), 'событий');
  assert.equal(leadingNumber('45.31.1 Торговля оптовая'), null);
  assert.equal(leadingNumber('5,3 млрд ₽ — 51 % из 10,4 млрд ₽'), '5,3 млрд ₽');
  assert.equal(leadingNumber('да'), null);
  assert.equal(leadingNumber('11 компаний, 7,5 млрд ₽ — 38 % выручки'), '11 компаний');
  assert.equal(leadingNumber('Более 251'), null);
  assert.equal(leadingNumber('16-100'), '16-100');
  assert.equal(leadingNumber('5–8 %'), '5–8 %');
});

const st = (origin: Statement['origin'], text: string, extra: Partial<Statement> = {}): Statement => ({ origin, text, refs: [], ...extra });

const insight: Insight = {
  id: 'ins:a',
  event: { title: 'ЦБ сохранил ставку', date: '2026-10-23' },
  relevance: { score: 0.65, reason: 'ставка × кредит' },
  what_happened: [st('fact', 'Банк России сохранил ставку 14 %.')],
  why_it_matters: [st('ai', 'Долг не подешевеет до конца 2026.')],
  consequences: {
    risks: [st('ai', 'Проценты останутся высокими'), st('estimate', 'Каждый 1 млрд долга — 140 млн ₽ в год')],
    opportunities: [st('hypothesis', 'Спрос на запчасти выдержит', { bank_conflict: { text: 'банк ждёт спада', refs: [] } })],
    factors: [],
  },
  bank_view: [st('bank', 'Банк ждёт 14 % до конца года', { refs: ['src:alfa:keyrate#p1'] })],
  actions: [{ text: 'Проверьте условия кредита', kind: 'product', product: 'credit', refs: [] }],
  sources: [
    { id: 'src:news:1', kind: 'news', title: 'a', publisher: 'Банк России', url: null, published_at: '2026-10-23T13:30:00' },
    { id: 'src:news:2', kind: 'news', title: 'b', publisher: 'Коммерсантъ', url: null, published_at: '2026-10-23' },
    { id: 'src:news:3', kind: 'news', title: 'c', publisher: 'Коммерсантъ', url: null, published_at: '2026-10-23' },
    { id: 'src:alfa:keyrate#p1', kind: 'alfa_analytics', title: 'Ключевая ставка ЦБ РФ', publisher: 'Альфа-Банк', url: null, published_at: '2026-09-11', page: 1, fragment: 'ожидаем её сохранения на 14,0 %' },
  ],
  features_used: ['feat:LOAN'],
  quality: { checks_passed: [], warnings: [] },
  trace_id: 'tr:a',
} as Insight;

test('карточка: цитата банка дословно с подписью, цифры из данных, целевое действие по фактору', () => {
  const c = cardScreen({ insight, item: item('a', 0.65, ['rate']), exposure });
  assert.equal(c.crumbs, 'Лента › Ставка');
  assert.deepEqual(
    c.sources.map((s) => [s.mark, s.label]),
    [
      ['ЦБ', 'Банк России · 23.10'],
      ['Ъ', 'Коммерсантъ · 2 статьи'],
    ],
  );
  assert.equal(c.forYou.quote?.text, '«ожидаем её сохранения на 14,0 %»');
  assert.equal(c.forYou.quote?.verbatim, true);
  assert.equal(c.forYou.quote?.caption, 'Аналитики Альфа-Банка · «Ключевая ставка ЦБ РФ» · 11.09.2026 · стр. 1');
  assert.deepEqual(c.forYou.numbers, [{ value: '11 из 28', label: 'Кредиты у компаний группы' }]);
  assert.equal(c.target?.topic, 'структуру долга');
  assert.ok(c.menu.some((m) => m.id === 'product' && m.label === 'Проверить условия кредита'));
  assert.equal(c.rows.find((r) => r.id === 'hypotheses')?.summary, '1 · 1 расходится с банком');
  assert.equal(c.estimates.length, 1);
});

test('карточка без риска — без целевого действия; без позиции банка — без цитаты', () => {
  const paraphrase = { ...insight, sources: insight.sources.map((s) => (s.kind === 'alfa_analytics' ? { ...s, id: 'src:alfa:keyrate#p2' } : s)) } as Insight;
  assert.equal(cardScreen({ insight: paraphrase, item: null, exposure: null }).forYou.quote?.verbatim, false);
  const calm = { ...insight, consequences: { risks: [], opportunities: [], factors: [] }, bank_view: [] } as Insight;
  const c = cardScreen({ insight: calm, item: null, exposure: null });
  assert.equal(c.target, null);
  assert.equal(c.forYou.quote, null);
  assert.equal(c.crumbs, 'Лента › Разбор');
});
