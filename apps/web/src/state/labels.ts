import type { Action, ChannelKind, Confidence, Feature, MissingFeature, Origin, Role, Source, Statement, Strength } from '../api/types';

/** Рабочее название сервиса — меняется здесь. */
export const SERVICE_NAME = 'Новости';

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
  hypothesis: 'Возможно',
};

export const originHint: Record<Origin, string> = {
  fact: 'подтверждено источником',
  data: 'из данных банка о вашей компании',
  bank: 'мнение аналитиков банка с датой и страницей материала',
  ai: 'интерпретация модели — проверьте по источникам',
  estimate: 'расчёт по формуле с допущениями',
  offer: 'продукт банка, не часть анализа',
  hypothesis: 'предположение модели, данными не подтверждено',
};

/**
 * Как показывать утверждение. Вывод модели с низкой уверенностью — это гипотеза: так его и подписываем,
 * чтобы факт, вывод и гипотеза различались с первого взгляда.
 */
export function displayOrigin(origin: Origin, confidence?: Confidence): Origin {
  return origin === 'ai' && confidence === 'low' ? 'hypothesis' : origin;
}

/** Расхождение с банком имеет смысл только у вывода модели и гипотезы; у факта или позиции банка поле игнорируем. */
export function bankConflictOf(statement: Pick<Statement, 'origin' | 'bank_conflict'>) {
  const c = statement.bank_conflict;
  return (statement.origin === 'ai' || statement.origin === 'hypothesis') && c && c.text ? c : null;
}

/** Что показываем в легенде карточки. */
export const legendOrigins: Origin[] = ['fact', 'data', 'bank', 'ai', 'hypothesis'];

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
  if (value === null) return 'нет данных';
  if (value === true) return 'есть';
  if (value === false) return 'нет';
  if (Array.isArray(value)) return value.join('; ');
  return String(value);
}

/** Признак для показа: готовая подпись из API, иначе значение. */
export function featureText(feature: Feature): string {
  return feature.display ?? featureValue(feature.value);
}

/** Чего нет в данных: объект из API или код поля в тестовых данных. */
export function missingText(item: MissingFeature | string): string {
  return typeof item === 'string' ? (missingLabel[item] ?? item) : item.label;
}

/** Страница материала банка: поле page или суффикс #pN в id. */
export function sourcePage(source: Source): number | null {
  if (source.page) return source.page;
  const m = /#p(\d+)$/.exec(source.id);
  return m ? Number(m[1]) : null;
}

const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' });
const dateYearFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.getFullYear() === new Date().getFullYear() ? dateFmt.format(d) : dateYearFmt.format(d);
}

/** Уровни значимости с определениями: что значит каждый уровень для руководителя. */
export const RELEVANCE_LEVELS = [
  {
    level: 3 as const,
    label: 'Высокая значимость',
    range: 'от 0,75',
    meaning:
      'Событие прямо меняет фактор, к которому компания сильно уязвима, и это видно в данных: ваш продукт в банке (кредит, депозит, гарантии), ваша отрасль или контрагенты от 30 % оборота.',
  },
  {
    level: 2 as const,
    label: 'Средняя значимость',
    range: '0,50–0,74',
    meaning: 'Фактор средней силы, или контрагенты на 10–30 % оборота, или влияние через компанию вашей группы.',
  },
  {
    level: 1 as const,
    label: 'Низкая значимость',
    range: 'до 0,49',
    meaning: 'Слабая связь или только отраслевой фон.',
  },
];

/** Оценка в интерфейсе — с округлением вниз до сотых, чтобы число и уровень не расходились на границе. */
export function relevanceScore(score: number): number {
  return Math.floor(score * 100 + 1e-9) / 100;
}

export function relevanceLevel(raw: number): { label: string; level: 1 | 2 | 3; meaning: string } {
  const score = relevanceScore(raw);
  const l = score >= 0.75 ? RELEVANCE_LEVELS[0] : score >= 0.5 ? RELEVANCE_LEVELS[1] : RELEVANCE_LEVELS[2];
  return { label: l.label, level: l.level, meaning: l.meaning };
}
