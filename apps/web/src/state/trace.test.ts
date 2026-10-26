// Тесты «Как получен вывод»: резюме из шагов реальной трассы (разбор решения ЦБ для казначея зернотрейдера) и
// очистка служебных id компаний из текстов.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Trace, TraceStep } from '../api/types.ts';
import { expandAbbr, scrubDeep, scrubIds, traceStory } from './trace.ts';

const step = (n: number, kind: TraceStep['kind'], extra: Partial<TraceStep> = {}): TraceStep => ({ n, kind, output_refs: [], ...extra });

const trace: Trace = {
  id: 'tr:1',
  steps: [
    step(1, 'tool', { tool: 'get_profile', summary: 'Компания №34911 · торговля оптовая зерном', output_refs: ['feat:A', 'feat:B'] }),
    step(2, 'tool', { tool: 'get_exposure_map', summary: 'факторы: rate=high', output_refs: ['feat:B', 'feat:C'] }),
    step(3, 'tool', { tool: 'get_counterparty_chain', summary: 'каналов нет: у события нет отраслей — цепочка через контрагентов не строится' }),
    step(4, 'tool', { tool: 'search_alfa_analytics', output_refs: ['src:alfa:keyrate-2026-09#p1-1', 'src:alfa:bondbrief#p1-1'] }),
    step(5, 'tool', { tool: 'search_alfa_analytics', output_refs: ['src:alfa:keyrate-2026-09#p1-6'] }),
    step(6, 'tool', { tool: 'search_news', output_refs: ['src:news:a', 'src:news:b', 'src:news:c'] }),
    step(7, 'tool', { tool: 'alfa_page_text', output_refs: ['src:alfa:keyrate-2026-09#p1'] }),
    step(8, 'tool', { tool: 'estimate_rate_impact' }),
    step(9, 'check', { verdict: 'fail', summary: 'why_it_matters[1]: суммы в рублях пишет только расчётный инструмент: 1 млрд ₽' }),
    step(10, 'retry', { summary: 'круг 1: 3 проблем(ы).' }),
    step(11, 'check', { verdict: 'fail', summary: 'why_it_matters[1]: чисел нет в данных о компании: 39' }),
    step(12, 'retry'),
    step(13, 'check', { verdict: 'fail', summary: 'итог после очистки (убрано 2): карточка: в «почему важно» нет данных о компании' }),
    step(14, 'check', { verdict: 'pass', summary: 'служебные предупреждения (не показаны): платёжная выгрузка покрывает 8 % выручки' }),
  ],
};

test('резюме трассы: что проверил, чего не нашёл, самопроверка с объяснением', () => {
  const s = traceStory(trace);
  assert.deepEqual(s.done, [
    'Посмотрел данные банка о компании: 3 признака',
    'Нашёл материалы аналитиков Альфа-Банка: 2, прочитал 1 страницу',
    'Нашёл другие новости по теме: 3',
    'Посчитал влияние в рублях по формуле с допущениями',
  ]);
  assert.deepEqual(s.missing, ['Цепочку через покупателей и поставщиков не построил: у события нет отраслей — цепочка через контрагентов не строится']);
  assert.equal(s.check.passed, false);
  assert.equal(
    s.check.text,
    'Итоговая самопроверка не пройдена. Модель исправляла ответ 2 раза. Осталось: в «почему важно» не было данных о компании. Такие места убраны из разбора: 2.',
  );
  assert.deepEqual(s.check.issues, [
    'суммы в рублях без расчёта по формуле',
    'числа, которых нет в данных о компании',
    'в «почему важно» не было данных о компании',
  ]);
});

test('самопроверка пройдена с первого раза и трасса без проверки', () => {
  const ok = traceStory({ id: 'tr:2', steps: [step(1, 'check', { verdict: 'pass', summary: 'всё сходится' })] });
  assert.equal(ok.check.passed, true);
  assert.match(ok.check.text, /^Самопроверка пройдена/);
  const none = traceStory({ id: 'tr:3', steps: [] });
  assert.deepEqual([none.done, none.missing, none.check.ran, none.check.text], [[], [], false, 'Самопроверка не выполнялась.']);
  const empty = traceStory({ id: 'tr:4', steps: [step(1, 'tool', { tool: 'search_alfa_analytics' })] });
  assert.deepEqual(empty.missing, ['Материалов Альфа-Банка по теме не нашёл']);
});

test('служебные id компаний убираем из текста, сами id не трогаем', () => {
  assert.equal(scrubIds('Компания №92457 закупает у U_4909 зерно'), 'Компания закупает у компания зерно');
  assert.equal(scrubIds('у компании №123 кредит'), 'у компании кредит');
  assert.equal(scrubIds('входит в число компаний №1 по выручке'), 'входит в число компаний №1 по выручке');
  assert.equal(scrubIds('Платёж. U_4909 закупает'), 'Платёж. Компания закупает');
  assert.equal(
    scrubIds('Проверьте с поставщиками (Компания №4754, Компания №153112, Компания №17010 — вместе 39 % оборота), не меняют ли цены.'),
    'Проверьте с поставщиками (3 компании — вместе 39 % оборота), не меняют ли цены.',
  );
  assert.equal(scrubIds('у U_101 и U_202 кредиты'), 'у 2 компании кредиты');
  assert.equal(scrubIds('U_57706'), 'U_57706');
  assert.equal(scrubIds('Крупные контрагенты: U_4754 · поставщик · 14 % оборота; U_909 · покупатель · 2 % оборота'), 'Крупные контрагенты: поставщик · 14 % оборота; покупатель · 2 % оборота');
  const body = scrubDeep({ company_id: 'U_57706', items: [{ text: 'Кредиты у Компания №333 и U_909' }], n: 3, ok: true, none: null });
  assert.deepEqual(body, { company_id: 'U_57706', items: [{ text: 'Кредиты у 2 компании' }], n: 3, ok: true, none: null });
});

test('сокращения расшифрованы при первом упоминании, «п.п.» — словами', () => {
  assert.equal(expandAbbr('ВЭД со странами ЕАЭС; ВЭД: Киргизия'), 'Внешняя торговля со странами ЕАЭС; ВЭД: Киргизия');
  assert.equal(expandAbbr('доля по ВЭД выросла'), 'доля по внешней торговле выросла');
  assert.equal(expandAbbr('ставка выше на 0,5 п.п. и на 2 п. п.'), 'ставка выше на 0,5 процентного пункта и на 2 процентных пункта.');
  assert.equal(expandAbbr('рост ФОТ на 5 п.п.'), 'рост ФОТ (фонд оплаты труда) на 5 процентных пунктов.');
  assert.equal(expandAbbr('ВЭД'), 'ВЭД');
  assert.equal(expandAbbr('доля ВЭД растёт'), 'доля внешней торговли растёт');
  assert.equal(expandAbbr('выше на 2 п.п. Это давит на маржу'), 'выше на 2 процентных пункта. Это давит на маржу');
  assert.equal(expandAbbr('рост на 2 п.п.'), 'рост на 2 процентных пункта.');
  assert.equal(expandAbbr('новые ВЭД-контракты и ВЭД группы'), 'новые ВЭД-контракты и ВЭД группы');
  assert.deepEqual(scrubDeep({ title: 'ВЭД под санкциями', text: 'ВЭД под санкциями' }), {
    title: 'ВЭД под санкциями',
    text: 'Внешняя торговля под санкциями',
  });
  assert.equal(expandAbbr('СВЭДЕНИЯ о компании'), 'СВЭДЕНИЯ о компании');
});
