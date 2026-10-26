// Тесты «Моих чисел»: разбор ввода и вопрос агенту только по введённым полям.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { EMPTY_NUMBERS, fromInputs, numbersQuestion, parseAmount, toInputs } from './mynumbers.ts';

test('числа: пробелы и запятая, пустое и мусор — не число', () => {
  assert.equal(parseAmount('2 000'), 2000);
  assert.equal(parseAmount('1,5'), 1.5);
  assert.equal(parseAmount(''), null);
  assert.equal(parseAmount('0'), null);
  assert.equal(parseAmount('-5'), null);
  assert.equal(parseAmount('много'), null);
});

test('вопрос агенту — только по заполненным полям', () => {
  assert.equal(numbersQuestion(EMPTY_NUMBERS), null);
  // Intl разделяет разряды неразрывным пробелом — сравниваем с обычным.
  assert.equal(
    numbersQuestion({ debt: '2000', rate: 'floating', fxRevenue: '', fx: '', fxCurrency: '', fxBaseRate: '', fxScenarioRate: '', currentRate: '', scenarioRate: '', fuel: '' })?.replace(/\s/g, ' '),
    'Пересчитай для наших чисел: долг 2 000 млн ₽, ставка плавающая. Сколько это событие стоит нам в рублях и при каких допущениях?',
  );
  assert.equal(
    numbersQuestion({ debt: '', rate: 'unknown', fxRevenue: '400', fx: '150', fxCurrency: '', fxBaseRate: '', fxScenarioRate: '', currentRate: '', scenarioRate: '', fuel: '1,5' }),
    'Пересчитай для наших чисел: валютная выручка 400 млн ₽ в месяц; валютные закупки 150 млн ₽ в месяц; закупка топлива 1,5 т в месяц. Сколько это событие стоит нам в рублях и при каких допущениях?',
  );
});

test('тело для API: миллионы — в рубли, «не знаю» — null, и обратно в поля формы', () => {
  const body = toInputs({ debt: '2 000', rate: 'unknown', fxRevenue: '', fx: '1,5', fxCurrency: '', fxBaseRate: '', fxScenarioRate: '', currentRate: '', scenarioRate: '', fuel: '' });
  assert.deepEqual(body, { debt_rub: 2_000_000_000, rate_type: null, fx_revenue_month_rub: null, fx_purchases_month_rub: 1_500_000, fx_currency: null, fx_base_rate: null, fx_scenario_rate: null, current_rate_pct: null, scenario_rate_pct: null, fuel_purchase_month_t: null });
  assert.deepEqual(fromInputs({ ...body, rate_type: 'fixed', fuel_purchase_month_t: 120, fx_currency: 'USD', fx_base_rate: 90, fx_scenario_rate: 95, current_rate_pct: 16, scenario_rate_pct: 12 }), { debt: '2000', rate: 'fixed', fxRevenue: '', fx: '1,5', fxCurrency: 'USD', fxBaseRate: '90', fxScenarioRate: '95', currentRate: '16', scenarioRate: '12', fuel: '120' });
});

test('Scenario inputs round-trip through the form and API', () => {
  const body = toInputs({ ...EMPTY_NUMBERS, fxRevenue: '400', fx: '150', fxCurrency: 'usd', fxBaseRate: '90', fxScenarioRate: '95', currentRate: '16', scenarioRate: '12' });
  assert.equal(body.fx_currency, 'USD');
  assert.equal(body.fx_base_rate, 90);
  assert.equal(body.fx_scenario_rate, 95);
  assert.equal(body.scenario_rate_pct, 12);
  assert.deepEqual(fromInputs(body), { ...EMPTY_NUMBERS, fxRevenue: '400', fx: '150', fxCurrency: 'USD', fxBaseRate: '90', fxScenarioRate: '95', currentRate: '16', scenarioRate: '12' });
});

test('explicit zero is retained, empty percentage inputs stay null', () => {
  const body = toInputs({ ...EMPTY_NUMBERS, debt: '0', currentRate: '', scenarioRate: '' });
  assert.equal(body.debt_rub, 0);
  assert.equal(body.current_rate_pct, null);
  assert.equal(body.scenario_rate_pct, null);
  assert.match(numbersQuestion({ ...EMPTY_NUMBERS, debt: '0' }) ?? '', /долга нет/);
});
