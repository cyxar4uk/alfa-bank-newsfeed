import type { Action, ChannelKind, Confidence, Feature, Origin, Role, Strength } from '../api/types';

/** Рабочее название сервиса — меняется здесь. */
export const SERVICE_NAME = 'Радар связей';

export const roleLabel: Record<Role, string> = {
  owner: 'Собственник',
  ceo: 'Генеральный директор',
  cfo: 'Финансовый директор',
  chief_accountant: 'Главный бухгалтер',
  treasury: 'Казначей',
  other: 'Руководитель',
};

export const originLabel: Record<Origin, string> = {
  fact: 'Факт · из источника',
  data: 'Данные о компании',
  bank: 'Позиция Альфа-Банка',
  ai: 'Вывод модели',
  estimate: 'Оценка',
  offer: 'Предложение банка',
};

export const originHint: Record<Origin, string> = {
  fact: 'подтверждено источником',
  data: 'из данных банка о вашей компании',
  bank: 'мнение аналитиков банка с датой и страницей материала',
  ai: 'интерпретация модели — проверьте по источникам',
  estimate: 'расчёт по формуле с допущениями',
  offer: 'продукт банка, не часть анализа',
};

/** Что показываем в легенде карточки. */
export const legendOrigins: Origin[] = ['fact', 'data', 'bank', 'ai'];

export const channelLabel: Record<ChannelKind, string> = {
  direct: 'Прямо',
  buyers: 'Через покупателей',
  suppliers: 'Через поставщиков',
  group: 'Через группу',
};

export const strengthLabel: Record<Strength, string> = {
  high: 'высокая',
  medium: 'средняя',
  low: 'низкая',
  none: 'нет',
  no_data: 'нет данных',
};

export const confidenceLabel: Record<Confidence, string> = {
  high: 'высокая уверенность',
  medium: 'средняя уверенность',
  low: 'низкая уверенность',
};

export const actionKindLabel: Record<Action['kind'], string> = {
  question: 'Вопрос для анализа',
  scenario: 'Сценарий',
  product: 'Продукт банка',
};

/** Коды полей набора данных → по-человечески, для предупреждений «чего не хватает». */
export const missingLabel: Record<string, string> = {
  REVENUE_COMPANY: 'выручка',
  FTS_COUNTRY_NAME: 'внешнеэкономическая деятельность',
  AMOUNT_WORKERS_SPARK_GRADATION: 'численность сотрудников',
  GROUP_ID: 'группа компаний',
};

export function featureValue(value: Feature['value']): string {
  if (value === true) return 'есть';
  if (value === false) return 'нет';
  if (Array.isArray(value)) return value.join('; ');
  return String(value);
}

const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' });
const dateYearFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.getFullYear() === new Date().getFullYear() ? dateFmt.format(d) : dateYearFmt.format(d);
}

export function relevanceLevel(score: number): { label: string; level: 1 | 2 | 3 } {
  if (score >= 0.75) return { label: 'Высокая значимость', level: 3 };
  if (score >= 0.5) return { label: 'Средняя значимость', level: 2 };
  return { label: 'Низкая значимость', level: 1 };
}
