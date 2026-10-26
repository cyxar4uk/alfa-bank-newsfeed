// Тесты доверия к выводу: готовность разбора, сводка проверки утверждений, сигнал «прогноз банка разошёлся».
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Insight, RiskMap } from '../api/types.ts';
import { claimsOf, outdatedSignals, readinessOf } from './trust.ts';

test('готовность разбора: insight_state главнее старого insight_ready', () => {
  assert.equal(readinessOf({ insight_state: 'ready' }), 'ready');
  assert.equal(readinessOf({ insight_state: 'queued', insight_ready: true }), 'queued');
  assert.equal(readinessOf({ insight_state: 'none', insight_ready: true }), null);
  assert.equal(readinessOf({ insight_ready: true }), 'ready');
  assert.equal(readinessOf({ insight_ready: false }), null);
  assert.equal(readinessOf({}), null);
});

test('проверка утверждений: счёт из claims_summary или по статусам, предположение — «Возможно»', () => {
  assert.equal(claimsOf({}), null);
  const v = claimsOf({
    claims: [
      { text: 'Ставка 14 % сохранена', status: 'verified', support: [{ kind: 'news', ref: 'src:news:1', quote: 'Банк России сохранил ставку 14 %' }] },
      {
        text: 'Долг дороже',
        status: 'partly',
        support: [{ kind: 'company', ref: 'feat:LOAN', quote: 'Кредиты в банке: есть' }, { kind: 'company', ref: 'feat:LOAN', quote: 'Кредиты в банке: есть' }, { kind: 'bank' }],
        unsupported_numbers: ['39 %'],
      },
      { text: 'Поставщики поднимут цены', status: 'hypothesis' },
    ],
  });
  assert.equal(v?.label, '1 из 3 утверждений подтверждено, предположение — 1');
  assert.equal(v?.allVerified, false);
  assert.equal(v?.rows[2].text, 'Возможно, поставщики поднимут цены');
  assert.deepEqual(v?.rows[1].support, [
    { kind: 'company', quote: 'Кредиты в банке: есть' },
    { kind: 'bank', quote: null },
  ]);
  assert.deepEqual(v?.rows[1].unsupported, ['39 %']);
  const all = claimsOf({ claims: [{ text: 'a', status: 'verified' }], claims_summary: { total: 12, verified_count: 12 } });
  assert.equal(all?.label, '12 из 12 утверждений подтверждены');
  assert.equal(all?.allVerified, true);
  // счёт говорит «все», а в списке предположение — зелёной отметки нет; счёт больше всего — обрезаем
  const odd = claimsOf({ claims: [{ text: 'ЦБ повысит ставку', status: 'hypothesis' }], claims_summary: { total: 3, verified_count: 5, hypothesis_count: 2 } });
  assert.equal(odd?.label, '3 из 3 утверждений подтверждены, предположения — 2');
  assert.equal(odd?.allVerified, false);
  assert.equal(odd?.rows[0].text, 'Возможно, ЦБ повысит ставку');
  assert.equal(claimsOf({ claims: [{ text: 'a', status: 'partly' }], claims_summary: { total: 21, verified_count: 21 } })?.label, '21 из 21 утверждения подтверждено');
  assert.equal(claimsOf({ claims: [{ text: 'a', status: 'partly' }] })?.label, '0 из 1 утверждения подтверждено');
});

test('прогноз банка разошёлся: факторы карты и позиция банка в разборе, без повторов', () => {
  const map = {
    company_id: 'U',
    role: 'cfo',
    week: [],
    limits: [],
    factors: [
      { code: 'fx', label: 'Курс рубля', strength: 'strong', why: '', is_estimate: false, week_counts: [], news_count: 0, bank: { text: 'Банк ждёт 87 ₽/$', outdated: true, outdated_note: 'банк ждал 87 ₽/$, в новостях — 80,6' } },
      { code: 'rate', label: 'Ставка', strength: 'strong', why: '', is_estimate: false, week_counts: [], news_count: 0, bank: { text: '14 %', outdated: false } },
    ],
  } as RiskMap;
  assert.deepEqual(outdatedSignals(map, null), [{ topic: 'Курс рубля', text: 'банк ждал 87 ₽/$, в новостях — 80,6' }]);
  const lead = { event: { title: 'Нефть дорожает' }, bank_position: { statement: 'Банк ждал Urals $63', outdated: true } } as Insight;
  assert.deepEqual(outdatedSignals(null, lead), [{ topic: 'Нефть дорожает', text: 'Банк ждал Urals $63 — прогноз устарел' }]);
  assert.deepEqual(outdatedSignals(null, null), []);
});
