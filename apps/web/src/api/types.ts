// Типы по черновику контракта (профиль, материал, инсайт, трасса) и спецификации продукта «Радар связей».
// После согласования источник правды — OpenAPI бэкенда; здесь держим зеркало для интерфейса.
// Поля, которых нет в черновике контракта, помечены «предложение фронта» — их нужно согласовать с API.

/**
 * fact — из новости или первоисточника, bank — позиция аналитиков Альфа-Банка, ai — вывод модели,
 * data — из данных банка о компании, estimate — расчёт по формуле, offer — предложение продукта банка.
 * data, estimate и offer добавлены по спецификации продукта, в черновике контракта их ещё нет.
 */
export type Origin = 'fact' | 'bank' | 'ai' | 'data' | 'estimate' | 'offer' | 'hypothesis';
export type Confidence = 'high' | 'medium' | 'low';

/** Единица любого вывода: текст, происхождение и ссылки на источники и признаки компании. */
export interface Statement {
  text: string;
  origin: Origin;
  /** id из `sources[]` (src:…) и признаков компании (feat:…) */
  refs: string[];
  confidence?: Confidence;
  /**
   * Вывод модели или гипотеза расходится с позицией Альфа-Банка: в чём именно и на какой материал банка опираемся
   * (refs — источники `alfa_analytics` из `sources`). Предложение фронта. У утверждений другого происхождения
   * интерфейс поле не показывает.
   */
  bank_conflict?: { text: string; refs: string[] } | null;
  /** Для гипотезы: что её подтвердит и что опровергнет (эталоны разборов, Q44). Предложение фронта. */
  check?: { confirm?: string | null; refute?: string | null } | null;
}

export interface Feature {
  id: string;
  label: string;
  value: string | number | boolean | string[] | null;
  /** значение для показа человеку, если value — число или код */
  display?: string | null;
  source: 'dataset' | 'derived';
  derived_from?: string[];
}

/** Признак, которого нет в данных, — показываем честно. */
export interface MissingFeature {
  id: string;
  label: string;
  reason?: string;
}

export interface CompanyProfile {
  id: string;
  display_name: string;
  features: Feature[];
  group?: { id: string; size?: number; members: string[] } | null;
  /** чего нет в данных: объекты из API или коды полей в тестовых данных */
  missing: (MissingFeature | string)[];
  /** что исправлено или отброшено при сборке профиля */
  data_notes?: string[];
  /** место по выручке среди компаний того же ОКВЭД в данных банка */
  industry?: { okved: string; rank: number; total: number } | null;
}

export type Role = 'owner' | 'ceo' | 'cfo' | 'chief_accountant' | 'treasury' | 'other';

export interface Persona {
  id: string;
  company_id: string;
  role: Role;
  name: string;
  role_label?: string;
  /** короткая обезличенная подпись компании: «Оптовик автозапчастей, Москва» */
  company_name?: string;
  sector?: string | null;
}

export interface Health {
  status: 'ok' | 'degraded';
  db: 'ok' | 'unavailable';
  data?: { file: string; rows_read: number; rows_loaded: number; rows_skipped: number; loaded_at: string }[];
}

export interface Source {
  id: string;
  kind: 'news' | 'alfa_analytics';
  title: string;
  publisher?: string | null;
  /** пусто — у материала нет публичной ссылки (например, PDF аналитики из пакета кейса) */
  url?: string | null;
  published_at?: string | null;
  /** страница материала банка; в тестовых данных она же в id: src:alfa:…#p3 */
  page?: number | null;
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

// ─── Трасса агента (критерий 11) ─────────────────────────────────────────────

export interface TraceStep {
  n: number;
  kind: 'plan' | 'tool' | 'llm' | 'check' | 'retry';
  summary?: string | null;
  tool?: string | null;
  input?: Record<string, unknown> | null;
  output_refs?: string[];
  model?: string | null;
  purpose?: string | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_rub?: number | null;
  verdict?: 'pass' | 'fail' | null;
}

export interface Trace {
  id: string;
  insight_id?: string | null;
  steps: TraceStep[];
  /** источники и признаки, на которые ссылаются шаги — предложение фронта */
  sources?: Source[];
  features_used?: string[];
  /** пояснение о происхождении трассы, например «восстановлена по тестовым данным» */
  note?: string;
  /** человеческое резюме от агента: что проверено, что не нашлось; нет — собираем из шагов */
  summary?: string[] | null;
}

// ─── Уточняющий вопрос и своя новость ────────────────────────────────────────

/** Ответ на уточняющий вопрос: утверждения с происхождением и ссылками. Предложение фронта. */
export interface AskAnswer {
  question: string;
  answer: Statement[];
  sources: Source[];
  /** вопрос не по теме разбора: вежливый отказ вместо ответа */
  refusal?: string | null;
  warnings?: string[];
}

/** Карта чувствительности в формате API: фактор → сила, канал и доказательства из данных банка. */
export interface CompanyExposure {
  company_id: string;
  factors: ExposureFactor[];
  warnings: string[];
}

export interface ExposureFactor {
  code: string;
  label: string;
  strength: number | null;
  level: Strength;
  channel: { kind: ChannelKind; text: string } | null;
  /** признак компании или число из данных: «Платежи импортёрам группы — 44 %» */
  evidence: { ref: string; label: string; value: string }[];
  estimate: boolean;
}

/** Сборка карточки в фоне (GET /api/insights/{id}?wait=false → 202, затем /status). */
export interface JobStatus {
  insight_id: string;
  event_id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  stage: string;
  stages_done: string[];
  elapsed_s: number;
  eta_s: number | null;
  queue_position: number | null;
  error: string | null;
  trace_id: string | null;
  /** живой ход разбора человеческим языком (07_feedback §3); нет — показываем stages_done */
  steps?: AgentStep[] | null;
  /** сколько шагов в плане разбора — для «шаг 7 из 12»; нет — пишем только номер шага */
  steps_total?: number | null;
}

export interface AgentStep {
  title: string;
  detail?: string | null;
  state: 'running' | 'done' | 'error';
  /** что нашёл на шаге: источники, материал банка, цифры компании */
  found?: string[] | null;
}

/** Вывод ленты одной фразой: важно ли, почему (число), что делать. */
export interface Takeaway {
  level: 'act' | 'watch' | 'info';
  text: string;
}

/** Новость целиком: GET /api/events/{id}. */
export interface EventDetail {
  id: string;
  /** новость: заголовок, издание, дата, первый абзац (fragment), ссылка и картинка */
  source?: (Pick<Source, 'title' | 'publisher' | 'url' | 'published_at' | 'fragment'> & { image_url?: string | null }) | null;
  /** полный текст, если получен законно; нет — показываем fragment */
  text?: string | null;
  image_url?: string | null;
  source_icon_url?: string | null;
  url?: string | null;
}

/** Каталог источников: GET /api/sources/catalog. */
export interface CatalogSource {
  id: string;
  name: string;
  country: 'ru' | 'intl';
  kind: 'free' | 'paid_api';
  reliability?: string | number | null;
  topics?: string[];
  connected: boolean;
  how_to_connect?: string[];
  docs_url?: string | null;
  icon_url?: string | null;
  /** ограничение для руководителя («сейчас недоступно в России») */
  note?: string | null;
  /** что это за источник — для руководителя */
  about?: string | null;
  /** что даст подключение — одной фразой */
  benefit?: string | null;
  /** бесплатно или по подписке, человеческим языком */
  access?: string | null;
  /** особенно полезен отрасли пользователя — для фильтра «Для вашей отрасли» */
  for_your_industry?: boolean | null;
  /** service — открытую ленту читает сервис; user — пользователь отметил сам */
  connected_by?: 'service' | 'user' | null;
  /** показывать ли «Отключить» */
  can_disconnect?: boolean | null;
  /** те же поля в другом варианте API (#80): пишет о сильных факторах компании; что даст подключение */
  relevant?: boolean | null;
  gives?: string | null;
}

/** Ответ на «Подключить» и «Отключить»: источник после изменения и что произошло. */
export interface SourceConnection {
  source: CatalogSource;
  message: string;
}

/** «Мои числа» пользователя: PUT/GET /api/personas/{persona}/inputs — агент берёт их в расчёт рублей. */
export interface PersonaInputs {
  debt_rub: number | null;
  rate_type: 'floating' | 'fixed' | null;
  /** валютная выручка в месяц — если API её принимает */
  fx_revenue_month_rub?: number | null;
  fx_purchases_month_rub: number | null;
  fuel_purchase_month_t: number | null;
  updated_at?: string | null;
}

export type InsightResult =
  | { kind: 'ready'; insight: Insight }
  | { kind: 'building'; job: JobStatus }
  /** событие не касается компании пользователя */
  | { kind: 'none' };

/** Запрос разбора своей новости: ссылка или текст. */
export interface AnalyzeRequest {
  persona_id: string;
  url?: string;
  text?: string;
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

/** Утверждение разбора и чем оно подтверждено: новостью, позицией банка, данными банка о компании. */
export interface Claim {
  text: string;
  status: 'verified' | 'partly' | 'hypothesis';
  /** опоры: quote — предложение источника или «признак: значение»; ref — src:… из sources или feat:… */
  support?: { kind: 'news' | 'bank' | 'company'; ref?: string | null; quote?: string | null }[] | null;
  /** числа утверждения, которым не нашлось опоры */
  unsupported_numbers?: string[] | null;
}

/** Итог проверки утверждений. */
export interface ClaimsSummary {
  total: number;
  verified_count: number;
  partly_count?: number | null;
  hypothesis_count?: number | null;
  /** сколько утверждений переписано и убрано при проверке */
  rewritten?: number | null;
  removed?: number | null;
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
  trace_id?: string | null;
  // Предложение фронта по спецификации продукта:
  exposure?: Exposure | null;
  /** дисклеймер от API; нет — берём свой */
  disclaimer?: string;
  /** итог «важно ли и что делать» (07_feedback §3) */
  verdict?: { level: Takeaway['level']; headline: string; why?: string | null; actions?: string[] } | null;
  /** позиция банка одной фразой «Альфа-Банк ожидает …» */
  /** outdated — прогноз банка разошёлся с фактом; outdated_note — «банк ждал 87 ₽/$, сейчас 80,6» */
  bank_position?: { statement: string; outdated?: boolean | null; outdated_note?: string | null } | null;
  /** проверка утверждений агентом: что подтверждено и чем */
  claims?: Claim[] | null;
  claims_summary?: ClaimsSummary | null;
  /** цитаты из новости, на которые опирается вывод — подсветка в полном тексте */
  quotes?: { text: string; source_id: string }[] | null;
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
  /** короткая строка «для вас» из данных (≤ 90 знаков); null — короткой нет */
  short?: string | null;
  /** разбор текущей версии уже собран — его можно взять с cached=true без сборки */
  insight_ready?: boolean | null;
  /** разбор собран заранее (ready), готовится (queued) или не нужен (none) */
  insight_state?: 'ready' | 'queued' | 'none' | null;
  /** продукты банка под это событие; owned — уже есть у компании */
  products?: { code: string; name: string; why?: string | null; link?: string | null; owned?: boolean | null }[] | null;
  /** вывод одной фразой с уровнем (07_feedback §3) */
  takeaway?: Takeaway | null;
  /** картинка новости (og:image источника) и значок издания */
  image_url?: string | null;
  source_icon_url?: string | null;
}

/** Динамика сюжета за неделю: появился · усилился · утих · держится (ровный поток). */
export type Dynamics = 'appeared' | 'grew' | 'faded' | 'steady';

/** Сюжет недели: события одной темы за 7 дней (GET /api/briefing?period=week). */
export interface Story {
  /** тема: код фактора или «industry:<ОКВЭД>» */
  code: string;
  /** суть главного события */
  title: string;
  level: Takeaway['level'];
  dynamics: Dynamics;
  /** новостей по теме по дням — дни в Briefing.week */
  daily_counts: number[];
  news_count: number;
  peak?: { date: string; what: string; event_id: string } | null;
  /** вывод главного события сюжета, с охватом группы */
  takeaway?: Takeaway | null;
  /** события сюжета — главное первым */
  event_ids: string[];
  /** разбор главного события сюжета: собран заранее, готовится или не нужен */
  insight_state?: 'ready' | 'queued' | 'none' | null;
}

/** Позиция Альфа-Банка по теме недели или фактору: фраза из материала, материал и дата. */
export interface BankView {
  text: string;
  source_id?: string | null;
  material?: string | null;
  publisher?: string | null;
  date?: string | null;
  /** прогноз банка разошёлся с фактом из новостей недели */
  outdated?: boolean | null;
  /** «банк ждал Urals $63, в новостях — $72» */
  outdated_note?: string | null;
}

/** Брифинг (раздел G): сводка и события по убыванию значимости. Плашка на главной — первые 3 отсюда. */
export interface Briefing {
  persona_id: string;
  /** 2–3 предложения «что изменилось для вас» */
  summary: Statement[];
  /** источники, на которые ссылается сводка */
  sources?: Source[];
  items: FeedItem[];
  /** сколько материалов рассмотрено */
  candidates?: number;
  /** day — лента; week — «Главное за неделю» */
  period?: 'day' | 'week';
  /** дни недели для daily_counts, от 6 дней назад до сегодня — только week */
  week?: string[];
  /** 3–5 сюжетов недели — только week */
  stories?: Story[];
  /** позиция банка по главной теме недели и главное действие — только week */
  bank?: BankView | null;
  action?: { code: string; topic: string; label: string; event_id?: string | null } | null;
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
  /** чего не хватает для полной карты */
  warnings?: string[];
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

// ─── «К чему уязвима компания» (макеты B2, B3): GET /api/companies/{id}/risk-map?persona= ──────

/** Сила влияния фактора: сильно · заметно · слабо. */
export type RiskStrength = 'strong' | 'notable' | 'weak';

export interface RiskFactor {
  code: string;
  label: string;
  strength: RiskStrength;
  /** почему компания уязвима — фраза с числом из данных банка */
  why: string;
  /** оценка по отрасли, а не факт из данных компании */
  is_estimate: boolean;
  /** что происходит на этой неделе — последнее событие; direction — «Дорожает», «Держится», «Новое» */
  now?: { event_id: string; title: string; direction: string; publisher?: string | null; date?: string | null } | null;
  bank?: BankView | null;
  /** новостей по дням — дни в RiskMap.week */
  week_counts: number[];
  news_count: number;
}

export interface RiskMap {
  company_id: string;
  role: Role;
  /** дни для week_counts: от 6 дней назад до сегодня */
  week: string[];
  /** 5–7 факторов в порядке, важном для роли */
  factors: RiskFactor[];
  /** чего не оцениваем и почему — с числом покрытия данных */
  limits: string[];
}
