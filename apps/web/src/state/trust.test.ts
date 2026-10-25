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

test('проверка утверждений: счёт из API или по статусам, предположение — «Возможно»', () => {
  assert.equal(claimsOf({}), null);
  const v = claimsOf({
    claims: [
      { text: 'Ставка 14 % сохранена', status: 'verified', support: [{ kind: 'news', label: 'Банк России, 23.10' }] },
      { text: 'Долг дороже', status: 'partly', support: [{ kind: 'data', label: null }, { kind: 'data' }, { kind: 'bank' }] },
      { text: 'Поставщики поднимут цены', status: 'hypothesis' },
    ],
  });
  assert.equal(v?.label, '1 из 3 утверждений подтверждено');
  assert.equal(v?.allVerified, false);
  assert.equal(v?.rows[2].text, 'Возможно, поставщики поднимут цены');
  assert.deepEqual(v?.rows[1].support, [
    { kind: 'data', label: 'Данные компании' },
    { kind: 'bank', label: 'Альфа-Банк' },
  ]);
  const all = claimsOf({ claims: [{ text: 'a', status: 'verified' }], verified_count: 12, claims_total: 12 });
  assert.equal(all?.label, '12 из 12 утверждений подтверждены');
  // счёт из API говорит «все», но в списке не только подтверждённые — зелёной отметки нет
  assert.equal(all?.allVerified, true);
  const odd = claimsOf({ claims: [{ text: 'ЦБ повысит ставку', status: 'hypothesis' }], verified_count: 5, claims_total: 3 });
  assert.equal(odd?.label, '3 из 3 утверждений подтверждены');
  assert.equal(odd?.allVerified, false);
  assert.equal(odd?.rows[0].text, 'Возможно, ЦБ повысит ставку');
  assert.equal(claimsOf({ claims: [{ text: 'a', status: 'partly' }], claims_total: 21, verified_count: 21 })?.label, '21 из 21 утверждения подтверждено');
  assert.equal(claimsOf({ claims: [{ text: 'a', status: 'partly' }] })?.label, '0 из 1 утверждения подтверждено');
});

test('прогноз банка разошёлся: факторы карты и позиция банка в разборе, без повторов', () => {
  const map = {
    company_id: 'U',
    role: 'cfo',
    week: [],
    limits: [],
    factors: [
      { code: 'fx', label: 'Курс рубля', strength: 'strong', why: '', is_estimate: false, week_counts: [], news_count: 0, bank: { text: 'Банк ждёт 87 ₽/$', outdated: true, outdated_note: 'Банк ждёт 87 ₽/$, сейчас 80,6' } },
      { code: 'rate', label: 'Ставка', strength: 'strong', why: '', is_estimate: false, week_counts: [], news_count: 0, bank: { text: '14 %', outdated: false } },
    ],
  } as RiskMap;
  assert.deepEqual(outdatedSignals(map, null), [{ topic: 'Курс рубля', text: 'Банк ждёт 87 ₽/$, сейчас 80,6' }]);
  const lead = { event: { title: 'Нефть дорожает' }, bank_position: { statement: 'Банк ждал Urals $63', outdated: true } } as Insight;
  assert.deepEqual(outdatedSignals(null, lead), [{ topic: 'Нефть дорожает', text: 'Банк ждал Urals $63 — прогноз устарел' }]);
  assert.deepEqual(outdatedSignals(null, null), []);
});
