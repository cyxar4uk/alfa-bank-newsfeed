// Тема события для вопросов и «Моих чисел»: курс, ставка, топливо или прочее. Подсказки и поля — под тему,
// а не одни на все карточки (замечание жюри: «Что при ставке 12 %?» на карточке про курс — как заготовка).
import type { FeedItem, Insight } from '../api/types.ts';

export type Topic = 'fx' | 'rate' | 'deposit' | 'fuel' | 'other';

function topicOfCode(code: string | undefined | null): Topic | null {
  if (!code) return null;
  if (code === 'fx') return 'fx';
  if (code === 'rate') return 'rate';
  if (code === 'deposit_yield') return 'deposit';
  if (code === 'commodity_oil' || code === 'oil') return 'fuel';
  return null;
}

/** Тема: фактор события из ленты, иначе фактор из оценки разбора, иначе по словам заголовка. */
export function topicOf(insight: Pick<Insight, 'event' | 'relevance'>, item: Pick<FeedItem, 'factors'> | null): Topic {
  const fromItem = topicOfCode(item?.factors[0]?.code);
  if (fromItem) return fromItem;
  const ref = (insight.relevance.refs ?? []).find((r) => r.startsWith('exp:'));
  const fromRefs = topicOfCode(ref?.slice(4));
  if (fromRefs) return fromRefs;
  const t = insight.event.title.toLowerCase();
  if (/курс|доллар|рубл|валют|юан/.test(t)) return 'fx';
  if (/депозит|вклад|размещени|доходност/.test(t)) return 'deposit';
  if (/ставк|кредит/.test(t)) return 'rate';
  if (/нефт|топлив|бензин|дизел|urals|brent/.test(t)) return 'fuel';
  return 'other';
}

/** Подсказки-вопросы с цифрами под тему; дальше — общие. */
export function topicQuestions(topic: Topic): string[] {
  switch (topic) {
    case 'fx':
      return ['Сколько это при 75 / 87 / 93 ₽/$?', 'Как защитить выручку от курса?'];
    case 'rate':
      return ['Что при ставке 12 / 16 %?', 'Сколько это в рублях?'];
    case 'deposit':
      return ['Какие сумму свободного остатка и срок размещения учитывать?'];
    case 'fuel':
      return ['Что при нефти $85?', 'Сколько это в рублях?'];
    default:
      return ['Сколько это в рублях?'];
  }
}

export type NumberField = 'debt' | 'fxRevenue' | 'fx' | 'fuel';

/** Какие «Мои числа» нужны для темы; прочие — под «Ещё поля». */
export function topicFields(topic: Topic): NumberField[] {
  switch (topic) {
    case 'fx':
      return ['fxRevenue', 'fx'];
    case 'rate':
      return ['debt'];
    case 'deposit':
      return [];
    case 'fuel':
      return ['fuel'];
    default:
      return ['debt', 'fxRevenue', 'fx', 'fuel'];
  }
}
