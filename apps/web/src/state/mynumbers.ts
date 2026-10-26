// «Мои числа»: пользователь подставляет свой долг, валютные закупки и закупку топлива — агент пересчитывает рубли.
// Числа сохраняются в API (PUT /api/personas/{persona}/inputs); пока метода нет — уходят вопросом в разбор (/ask).
// Фронт ничего не досчитывает: расчёт делают расчётные инструменты агента.
import type { PersonaInputs } from '../api/types.ts';

export type RateType = 'floating' | 'fixed' | 'unknown';

export interface MyNumbers {
  /** долг, млн ₽ */
  debt: string;
  rate: RateType;
  /** валютная выручка в месяц, млн ₽ — у экспортёров */
  fxRevenue: string;
  /** валютные закупки в месяц, млн ₽ */
  fx: string;
  fxCurrency: string;
  fxBaseRate: string;
  fxScenarioRate: string;
  currentRate: string;
  scenarioRate: string;
  /** закупка топлива в месяц, тонн */
  fuel: string;
}

export const EMPTY_NUMBERS: MyNumbers = { debt: '', rate: 'unknown', fxRevenue: '', fx: '', fxCurrency: '', fxBaseRate: '', fxScenarioRate: '', currentRate: '', scenarioRate: '', fuel: '' };

const RATE_TEXT: Record<RateType, string> = {
  floating: 'ставка плавающая',
  fixed: 'ставка фиксированная',
  unknown: 'тип ставки не знаю',
};

/** «2 000», «1,5» → число; пусто, ноль или мусор → null. */
export function parseAmount(value: string, allowZero = false): number | null {
  if (!value.trim()) return null;
  const n = Number(value.replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(n) && (n > 0 || (allowZero && n === 0)) ? n : null;
}

const fmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

/** Вопрос агенту по введённым числам; null — ничего не введено. */
export function numbersQuestion(nums: MyNumbers): string | null {
  const debt = parseAmount(nums.debt, true);
  const fx = parseAmount(nums.fx, true);
  const fxRevenue = parseAmount(nums.fxRevenue, true);
  const fuel = parseAmount(nums.fuel);
  const parts = [
    debt != null && nums.debt.trim() ? (debt === 0 ? 'долга нет (0 млн ₽)' : `долг ${fmt.format(debt)} млн ₽, ${RATE_TEXT[nums.rate]}`) : null,
    fxRevenue != null && nums.fxRevenue.trim() ? `валютная выручка ${fmt.format(fxRevenue)} млн ₽ в месяц` : null,
    fx != null && nums.fx.trim() ? `валютные закупки ${fmt.format(fx)} млн ₽ в месяц` : null,
    fuel != null ? `закупка топлива ${fmt.format(fuel)} т в месяц` : null,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return `Пересчитай для наших чисел: ${parts.join('; ')}. Сколько это событие стоит нам в рублях и при каких допущениях?`;
}

const key = (personaId: string) => `pulse.numbers.${personaId}`;

export function readNumbers(personaId: string): MyNumbers {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key(personaId)) ?? 'null');
    if (raw && typeof raw === 'object') {
      const r = raw as Partial<MyNumbers>;
      return {
        debt: typeof r.debt === 'string' ? r.debt : '',
        rate: r.rate === 'floating' || r.rate === 'fixed' ? r.rate : 'unknown',
        fxRevenue: typeof r.fxRevenue === 'string' ? r.fxRevenue : '',
        fx: typeof r.fx === 'string' ? r.fx : '',
        fxCurrency: typeof r.fxCurrency === 'string' ? r.fxCurrency : '',
        fxBaseRate: typeof r.fxBaseRate === 'string' ? r.fxBaseRate : '',
        fxScenarioRate: typeof r.fxScenarioRate === 'string' ? r.fxScenarioRate : '',
        currentRate: typeof r.currentRate === 'string' ? r.currentRate : '',
        scenarioRate: typeof r.scenarioRate === 'string' ? r.scenarioRate : '',
        fuel: typeof r.fuel === 'string' ? r.fuel : '',
      };
    }
  } catch {
    // нет хранилища или битые данные — пустая форма
  }
  return EMPTY_NUMBERS;
}

export function saveNumbers(personaId: string, nums: MyNumbers) {
  try {
    localStorage.setItem(key(personaId), JSON.stringify(nums));
  } catch {
    // без хранилища числа живут до перезагрузки
  }
}

/** Тело для PUT /api/personas/{persona}/inputs: миллионы — в рубли, пустое — null. */
export function toInputs(nums: MyNumbers): PersonaInputs {
  const mln = (v: string) => {
    const n = parseAmount(v, true);
    return n == null ? null : Math.round(n * 1_000_000);
  };
  return {
    debt_rub: mln(nums.debt),
    rate_type: nums.rate === 'unknown' ? null : nums.rate,
    fx_revenue_month_rub: nums.fxRevenue.trim() && parseAmount(nums.fxRevenue, true) != null ? Math.round(parseAmount(nums.fxRevenue, true)! * 1_000_000) : null,
    fx_purchases_month_rub: nums.fx.trim() && parseAmount(nums.fx, true) != null ? Math.round(parseAmount(nums.fx, true)! * 1_000_000) : null,
    fx_currency: nums.fxCurrency.trim() ? nums.fxCurrency.trim().toUpperCase() : null,
    fx_base_rate: parseAmount(nums.fxBaseRate),
    fx_scenario_rate: parseAmount(nums.fxScenarioRate),
    current_rate_pct: parseAmount(nums.currentRate, true),
    scenario_rate_pct: parseAmount(nums.scenarioRate, true),
    fuel_purchase_month_t: parseAmount(nums.fuel),
  };
}

/** Сохранённые на сервере числа → поля формы. */
export function fromInputs(i: PersonaInputs): MyNumbers {
  const mln = (v: number | null) => (v == null ? '' : String(Math.round((v / 1_000_000) * 10) / 10).replace('.', ','));
  return {
    debt: mln(i.debt_rub),
    rate: i.rate_type ?? 'unknown',
    fxRevenue: mln(i.fx_revenue_month_rub ?? null),
    fx: mln(i.fx_purchases_month_rub),
    fxCurrency: i.fx_currency ?? '',
    fxBaseRate: i.fx_base_rate == null ? '' : String(i.fx_base_rate).replace('.', ','),
    fxScenarioRate: i.fx_scenario_rate == null ? '' : String(i.fx_scenario_rate).replace('.', ','),
    currentRate: i.current_rate_pct == null ? '' : String(i.current_rate_pct).replace('.', ','),
    scenarioRate: i.scenario_rate_pct == null ? '' : String(i.scenario_rate_pct).replace('.', ','),
    fuel: i.fuel_purchase_month_t == null ? '' : String(i.fuel_purchase_month_t).replace('.', ','),
  };
}
