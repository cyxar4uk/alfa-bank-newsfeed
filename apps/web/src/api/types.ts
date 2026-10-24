// Типы по черновику контракта (профиль, материал, инсайт, трасса) и спецификации продукта «Радар связей».
// После согласования источник правды — OpenAPI бэкенда; здесь держим зеркало для интерфейса.
// Поля, которых нет в черновике контракта, помечены «предложение фронта» — их нужно согласовать с API.

/**
 * fact — из новости или первоисточника, bank — позиция аналитиков Альфа-Банка, ai — вывод модели,
 * data — из данных банка о компании, estimate — расчёт по формуле, offer — предложение продукта банка.
 * data, estimate и offer добавлены по спецификации продукта, в черновике контракта их ещё нет.
 */
export type Origin = 'fact' | 'bank' | 'ai' | 'data' | 'estimate' | 'offer';
export type Confidence = 'high' | 'medium' | 'low';

/** Единица любого вывода: текст, происхождение и ссылки на источники и признаки компании. */
export interface Statement {
  text: string;
  origin: Origin;
  /** id из `sources[]` (src:…) и признаков компании (feat:…) */
  refs: string[];
  confidence?: Confidence;
}

export interface Feature {
  id: string;
  label: string;
  value: string | number | boolean | string[];
  source: 'dataset' | 'derived';
  derived_from?: string[];
}

export interface CompanyProfile {
  id: string;
  display_name: string;
  features: Feature[];
  group?: { id: string; members: string[] } | null;
  /** коды полей, которых нет в данных — показываем честно */
  missing: string[];
}

export type Role = 'owner' | 'ceo' | 'cfo' | 'chief_accountant' | 'treasury' | 'other';

export interface Persona {
  id: string;
  company_id: string;
  role: Role;
  name: string;
}

export interface Source {
  id: string;
  kind: 'news' | 'alfa_analytics';
  title: string;
  publisher: string;
  /** пусто — у материала нет публичной ссылки (например, PDF аналитики из пакета кейса) */
  url: string;
  published_at: string;
  fragment?: string;
  tags?: {
    topics?: string[];
    sectors?: string[];
    okved?: string[];
    event_type?: string;
    regions?: string[];
  };
}

export interface InsightEvent {
  title: string;
  date: string;
}

// ─── Факторы и каналы (спецификация, разделы A и B) ──────────────────────────

/** Код фактора из каталога: rate, fx, consumer, demand_56, commodity_oil… Каталог — конфиг на бэкенде. */
export interface FactorRef {
  code: string;
  label: string;
}

/** Как событие доходит до компании: прямо, через покупателей, через поставщиков, через группу. */
export type ChannelKind = 'direct' | 'buyers' | 'suppliers' | 'group';

/** Слагаемое оценки значимости — для «почему это выше остального». Предложение фронта. */
export interface ScoreTerm {
  label: string;
  value: number;
}

export interface Relevance {
  score: number;
  reason: string;
  refs: string[];
  /** разложение score на слагаемые; сумма равна score */
  breakdown?: ScoreTerm[];
}

export interface Action {
  text: string;
  kind: 'question' | 'scenario' | 'product';
  product?: string | null;
  refs: string[];
}

// ─── Блоки карточки по спецификации продукта (предложение фронта) ────────────

export interface Counterparty {
  id: string;
  /** обезличенная подпись: «импортёр запчастей, ВЭД ОАЭ, Индия, Китай» */
  label: string;
  /** доля в видимом банку обороте компании, 0–1 */
  share?: number | null;
  amount_bn?: number | null;
  intra_group?: boolean;
}

/** Канал цепочки «событие → фактор → контрагенты → вы» (раздел A). */
export interface ExposureChannel {
  kind: ChannelKind;
  factor: FactorRef;
  /** человеческим текстом: «рестораны и кафе — 53 % поступлений» */
  text: string;
  /** отрасль, через которую идёт связь, если канал не прямой */
  sector?: string | null;
  /** доля оборота, которую даёт канал, 0–1 */
  share?: number | null;
  /** доля оборота с известной отраслью контрагента, 0–1 */
  coverage?: number | null;
  counterparties: Counterparty[];
}

export interface Exposure {
  channels: ExposureChannel[];
  /** честные пробелы: «платежи компании покрывают < 1 % выручки — цепочек через контрагентов нет» */
  gaps: string[];
}

/** Влияние на группу компаний (раздел I). */
export interface GroupImpact {
  group_id: string;
  companies_total: number;
  affected_revenue_bn: number;
  affected: { id: string; label: string; revenue_bn: number; factors: FactorRef[] }[];
}

/** Банк против рынка (раздел F). Расхождение — только когда есть и позиция банка, и ожидание рынка. */
export interface BankVsMarket {
  verdict: 'agrees' | 'diverges';
  summary: string;
  bank: Statement;
  market?: Statement | null;
}

/** Оценка в рублях по формуле со сценариями (разделы C и E). Считается в интерфейсе, без вызова модели. */
export interface Estimate {
  id: string;
  title: string;
  /** формула человеческим текстом: «долг × изменение ставки» */
  formula: string;
  input: { label: string; unit: string; hint: string };
  result_label: string;
  scenarios: EstimateScenario[];
  assumptions: string[];
}

export interface EstimateScenario {
  id: 'base' | 'hard' | 'soft';
  label: string;
  /** результат = ввод × multiplier */
  multiplier: number;
  /** откуда параметр: прогноз банка или допущение сервиса */
  basis: Statement;
}

export interface Insight {
  id: string;
  event: InsightEvent;
  relevance: Relevance;
  what_happened: Statement[];
  why_it_matters: Statement[];
  consequences: {
    risks: Statement[];
    opportunities: Statement[];
    factors: Statement[];
  };
  bank_view: Statement[];
  actions: Action[];
  sources: Source[];
  features_used: string[];
  quality: {
    checks_passed: string[];
    warnings: string[];
  };
  trace_id: string;
  // Предложение фронта по спецификации продукта:
  exposure?: Exposure | null;
  group_impact?: GroupImpact | null;
  bank_vs_market?: BankVsMarket | null;
  estimates?: Estimate[];
}

/**
 * Элемент ленты: событие с оценкой значимости, без полного инсайта.
 * В черновике контракта форма не расписана — предложение фронта, согласовать с API.
 */
export interface FeedItem {
  event_id: string;
  event: InsightEvent;
  relevance: Relevance;
  /** есть ли по теме материал аналитиков банка */
  has_bank_view: boolean;
  /** главный источник события */
  source: Pick<Source, 'id' | 'kind' | 'title' | 'publisher' | 'url' | 'published_at'>;
  /** факторы компании, которые задевает событие — для фильтра брифинга */
  factors: FactorRef[];
  /** главный канал и он же человеческим текстом */
  channel: ChannelKind;
  channel_text: string;
}

/** Брифинг (раздел G): сводка и события по убыванию значимости. Плашка на главной — первые 3 отсюда. */
export interface Briefing {
  persona_id: string;
  /** 2–3 предложения «что изменилось для вас» */
  summary: Statement[];
  /** источники, на которые ссылается сводка */
  sources?: Source[];
  items: FeedItem[];
}

export interface Feedback {
  insight_id: string;
  persona_id: string;
  useful: boolean;
  reason?: string;
}

// ─── Будущие экраны (#30, #31): карта чувствительности и сводка недели ──────

export type Strength = 'high' | 'medium' | 'low' | 'none' | 'no_data';

export interface SensitivityFactor {
  factor: FactorRef;
  strength: Strength;
  /** «через покупателей из стройки, 31 % поступлений» */
  channel_text: string;
  evidence: Statement[];
  coverage?: number | null;
  recent_event_ids: string[];
}

/** Карта чувствительности компании (раздел B). */
export interface ExposureMap {
  company_id: string;
  factors: SensitivityFactor[];
  /** источники, на которые ссылаются доказательства */
  sources?: Source[];
  /** положение среди компаний того же ОКВЭД в данных банка */
  position?: { okved: string; rank: number; total: number } | null;
}

/** Сводка недели для совета директоров (раздел G). */
export interface WeeklySummary {
  persona_id: string;
  period: { from: string; to: string };
  /** источники, на которые ссылаются утверждения */
  sources?: Source[];
  sections: { factor: FactorRef; statements: Statement[] }[];
  bank_view: Statement[];
  actions: Action[];
}
