// Тесты темы события: вопросы и «Мои числа» под фактор, а не одни на все карточки.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Insight } from '../api/types.ts';
import { topicFields, topicOf, topicQuestions } from './topic.ts';

const ins = (title: string, refs: string[] = []) => ({ event: { title }, relevance: { score: 0.5, reason: '', refs } }) as unknown as Insight;

test('тема: фактор из ленты, из оценки разбора или по заголовку', () => {
  assert.equal(topicOf(ins('Что угодно'), { factors: [{ code: 'fx', label: 'Курс' }] }), 'fx');
  assert.equal(topicOf(ins('Что угодно', ['exp:commodity_oil']), null), 'fuel');
  assert.equal(topicOf(ins('Банк России сохранил ключевую ставку'), null), 'rate');
  assert.equal(topicOf(ins('Курс доллара на неделю'), null), 'fx');
  assert.equal(topicOf(ins('Урожай картофеля'), null), 'other');
});

test('вопросы и поля — под тему: на курсе нет вопроса про ставку, у экспортёра есть валютная выручка', () => {
  assert.deepEqual(topicQuestions('fx'), ['Сколько это при 75 / 87 / 93 ₽/$?', 'Как защитить выручку от курса?']);
  assert.ok(!topicQuestions('fx').some((q) => /ставк/.test(q)));
  assert.deepEqual(topicQuestions('rate'), ['Что при ставке 12 / 16 %?', 'Сколько это в рублях?']);
  assert.deepEqual(topicQuestions('fuel'), ['Что при нефти $85?', 'Сколько это в рублях?']);
  assert.deepEqual(topicFields('fx'), ['fxRevenue', 'fx']);
  assert.deepEqual(topicFields('rate'), ['debt']);
  assert.deepEqual(topicFields('other'), ['debt', 'fxRevenue', 'fx', 'fuel']);
});
