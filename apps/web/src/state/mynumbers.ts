// «Мои числа»: пользователь подставляет свой долг, валютные закупки и закупку топлива — агент пересчитывает рубли.
// Числа сохраняются в API (PUT /api/personas/{persona}/inputs); пока метода нет — уходят вопросом в разбор (/ask).
// Фронт ничего не досчитывает: расчёт делают расчётные инструменты агента.
import type { PersonaInputs } from '../api/types.ts';

export type RateType = 'floating' | 'fixed' | 'unknown';

export interface MyNumbers {
  /** долг, млн ₽ */
  debt: string;
  rate: RateType;
  /** валютные закупки в месяц, млн ₽ */
  fx: string;
  /** закупка топлива в месяц, тонн */
  fuel: string;
}

export const EMPTY_NUMBERS: MyNumbers = { debt: '', rate: 'unknown', fx: '', fuel: '' };

const RATE_TEXT: Record<RateType, string> = {
  floating: 'ставка плавающая',
  fixed: 'ставка фиксированная',
  unknown: 'тип ставки не знаю',
};

/** «2 000», «1,5» → число; пусто, ноль или мусор → null. */
export function parseAmount(value: string): number | null {
  const n = Number(value.replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(n) && n > 0 ? n : null;
}

const fmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

/** Вопрос агенту по введённым числам; null — ничего не введено. */
export function numbersQuestion(nums: MyNumbers): string | null {
  const debt = parseAmount(nums.debt);
  const fx = parseAmount(nums.fx);
  const fuel = parseAmount(nums.fuel);
  const parts = [
    debt != null ? `долг ${fmt.format(debt)} млн ₽, ${RATE_TEXT[nums.rate]}` : null,
    fx != null ? `валютные закупки ${fmt.format(fx)} млн ₽ в месяц` : null,
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
        fx: typeof r.fx === 'string' ? r.fx : '',
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
    const n = parseAmount(v);
    return n == null ? null : Math.round(n * 1_000_000);
  };
  return {
    debt_rub: mln(nums.debt),
    rate_type: nums.rate === 'unknown' ? null : nums.rate,
    fx_purchases_month_rub: mln(nums.fx),
    fuel_purchase_month_t: parseAmount(nums.fuel),
  };
}

/** Сохранённые на сервере числа → поля формы. */
export function fromInputs(i: PersonaInputs): MyNumbers {
  const mln = (v: number | null) => (v == null ? '' : String(Math.round((v / 1_000_000) * 10) / 10).replace('.', ','));
  return {
    debt: mln(i.debt_rub),
    rate: i.rate_type ?? 'unknown',
    fx: mln(i.fx_purchases_month_rub),
    fuel: i.fuel_purchase_month_t == null ? '' : String(i.fuel_purchase_month_t).replace('.', ','),
  };
}
