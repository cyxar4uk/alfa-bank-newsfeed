import type {
  AnalyzeRequest,
  AskAnswer,
  Briefing,
  CompanyProfile,
  ExposureMap,
  FeedItem,
  Feedback,
  Health,
  Insight,
  Persona,
  SensitivityFactor,
  Statement,
  Strength,
  Trace,
  WeeklySummary,
} from './types';
import { mockApi } from '../mocks/mockApi';

export interface Api {
  personas(signal?: AbortSignal): Promise<Persona[]>;
  company(id: string, signal?: AbortSignal): Promise<CompanyProfile>;
  /** брифинг: сводка и события по убыванию значимости для пользователя */
  briefing(personaId: string, signal?: AbortSignal): Promise<Briefing>;
  /** null — событие не касается компании пользователя */
  insight(eventId: string, personaId: string, signal?: AbortSignal): Promise<Insight | null>;
  feedback(body: Feedback): Promise<void>;
  /** карта чувствительности компании: к чему уязвима и через кого */
  exposureMap(companyId: string, signal?: AbortSignal): Promise<ExposureMap>;
  /** сводка недели для печати */
  weekly(personaId: string, signal?: AbortSignal): Promise<WeeklySummary>;
  health(signal?: AbortSignal): Promise<Health>;
  /** уточняющий вопрос по разбору */
  ask(insightId: string, personaId: string, question: string, signal?: AbortSignal): Promise<AskAnswer>;
  /** трасса агента; null — трассы нет */
  trace(traceId: string, signal?: AbortSignal): Promise<Trace | null>;
  /** разбор своей новости; null — новость не касается компании пользователя */
  analyze(body: AnalyzeRequest, signal?: AbortSignal): Promise<Insight | null>;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Разбор генерируется лениво и может идти до 30 с — даём запас. */
const TIMEOUT_MS = 45_000;

const asArray = <T>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

/** Брифинг принимаем целиком или голым списком событий; отсутствующие поля заменяем пустыми. */
function normalizeBriefing(personaId: string, raw: unknown): Briefing {
  const body = (Array.isArray(raw) ? { items: raw } : (raw ?? {})) as Partial<Briefing>;
  return {
    persona_id: personaId,
    summary: asArray(body.summary),
    sources: asArray(body.sources),
    items: asArray<FeedItem>(body.items).map((item) => ({ ...item, factors: asArray(item.factors) })),
  };
}

const STRENGTHS: Strength[] = ['high', 'medium', 'low', 'none', 'no_data'];

/** Фактор в формате API: сила числом и уровнем, канал объектом, доказательства «признак — значение». */
interface ApiFactor {
  code: string;
  label: string;
  level?: string;
  channel?: { kind?: string; text?: string } | null;
  evidence?: { ref?: string; label: string; value: string }[];
  estimate?: boolean;
  coverage?: number | null;
  notes?: string[];
}

function fromApiFactor(f: ApiFactor): SensitivityFactor {
  const origin: Statement['origin'] = f.estimate ? 'estimate' : 'data';
  return {
    factor: { code: f.code, label: f.label },
    strength: (f.level ?? 'no_data') as Strength,
    channel_text: f.channel?.text ?? asArray<string>(f.notes)[0] ?? '',
    evidence: [
      ...asArray<NonNullable<ApiFactor['evidence']>[number]>(f.evidence).map((e) => ({
        text: `${e.label}: ${e.value}`,
        origin,
        refs: e.ref?.startsWith('feat:') ? [e.ref] : [],
        confidence: 'high' as const,
      })),
      ...asArray<string>(f.notes).map((n) => ({ text: n, origin, refs: [], confidence: 'high' as const })),
    ],
    coverage: f.coverage ?? null,
    recent_event_ids: [],
  };
}

/** Карту принимаем и в формате фронта, и в формате API (`level`, `channel`, `evidence[] {ref,label,value}`). */
function normalizeMap(body: ExposureMap & { warnings?: unknown }): ExposureMap {
  return {
    ...body,
    sources: asArray(body.sources),
    warnings: asArray(body.warnings),
    factors: asArray<SensitivityFactor | ApiFactor>(body.factors).map((raw) => {
      const f = 'factor' in raw ? raw : fromApiFactor(raw);
      return {
        ...f,
        // Незнакомую силу показываем как «нет данных», а не как ноль.
        strength: STRENGTHS.includes(f.strength) ? f.strength : 'no_data',
        evidence: asArray(f.evidence),
        recent_event_ids: asArray(f.recent_event_ids),
      };
    }),
  };
}

function normalizeWeekly(personaId: string, body: WeeklySummary): WeeklySummary {
  return {
    ...body,
    persona_id: personaId,
    period: { from: body.period?.from ?? '', to: body.period?.to ?? '' },
    sections: asArray<WeeklySummary['sections'][number]>(body.sections).map((s) => ({
      ...s,
      statements: asArray(s.statements),
    })),
    bank_view: asArray(body.bank_view),
    actions: asArray(body.actions),
    sources: asArray(body.sources),
  };
}

function createHttpApi(baseUrl: string): Api {
  const base = baseUrl.replace(/\/$/, '');

  /** Ответ сервера: тело в JSON или пусто для 204. */
  async function request<T>(path: string, init: RequestInit = {}): Promise<{ status: number; body?: T }> {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), TIMEOUT_MS);
    const outer = init.signal;
    const onOuterAbort = () => timeout.abort();
    if (outer?.aborted) timeout.abort();
    outer?.addEventListener('abort', onOuterAbort);

    try {
      let res: Response;
      let text: string;
      try {
        res = await fetch(`${base}${path}`, { ...init, signal: timeout.signal });
        text = await res.text();
      } catch (e) {
        if (outer?.aborted) throw e;
        throw new ApiError(0, timeout.signal.aborted ? 'Сервер не ответил за 45 секунд' : 'Сервер не отвечает');
      }
      if (!res.ok) throw new ApiError(res.status, `Сервер вернул ошибку ${res.status}`);
      if (res.status === 204) return { status: 204 };
      if (!text) {
        // Для POST пустое тело — нормальный ответ «принято».
        if (init.method === 'POST') return { status: res.status };
        throw new ApiError(res.status, 'Сервер вернул пустой ответ');
      }
      try {
        return { status: res.status, body: JSON.parse(text) as T };
      } catch {
        throw new ApiError(res.status, 'Сервер вернул ответ не в формате JSON');
      }
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener('abort', onOuterAbort);
    }
  }

  async function required<T>(path: string, signal?: AbortSignal): Promise<T> {
    const { body } = await request<T>(path, { signal });
    if (body === undefined) throw new ApiError(204, 'Сервер не вернул данных');
    return body;
  }

  const q = encodeURIComponent;

  return {
    personas: (signal) => required(`/api/personas`, signal),
    company: (id, signal) => required(`/api/companies/${q(id)}`, signal),
    briefing: async (personaId, signal) =>
      normalizeBriefing(personaId, await required<unknown>(`/api/briefing?persona=${q(personaId)}`, signal)),
    // 204 — событие не касается компании пользователя.
    insight: async (eventId, personaId, signal) => {
      const { body } = await request<Insight>(`/api/insights/${q(eventId)}?persona=${q(personaId)}`, { signal });
      return body ?? null;
    },
    exposureMap: async (companyId, signal) =>
      normalizeMap(await required<ExposureMap>(`/api/companies/${q(companyId)}/exposure`, signal)),
    weekly: async (personaId, signal) =>
      normalizeWeekly(personaId, await required<WeeklySummary>(`/api/weekly?persona=${q(personaId)}`, signal)),
    feedback: async (body) => {
      await request<unknown>(`/api/feedback`, post(body));
    },
    health: (signal) => required(`/api/health`, signal),
    ask: async (insightId, personaId, question, signal) => {
      const { body } = await request<AskAnswer>(`/api/insights/${q(insightId)}/ask`, {
        ...post({ persona: personaId, question }),
        signal,
      });
      if (!body) throw new ApiError(204, 'Сервер не вернул ответ');
      return { question, answer: asArray(body.answer), sources: asArray(body.sources) };
    },
    trace: async (traceId, signal) => {
      const { body } = await request<Trace>(`/api/traces/${q(traceId)}`, { signal });
      return body ? { ...body, steps: asArray(body.steps), sources: asArray(body.sources) } : null;
    },
    analyze: async (req, signal) => {
      const { body } = await request<Insight>(`/api/analyze`, { ...post(req), signal });
      return body ?? null;
    },
  };
}

function post(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

type ApiMethod = keyof Api;

/**
 * Пока в API есть не все методы, часть берём из тестовых данных. Список методов из настоящего API —
 * VITE_API_LIVE через запятую (по умолчанию то, что уже есть в API), `all` — всё из API.
 */
// Разбор, вопросы по нему, трасса и своя новость — одно целое: ответ и трасса должны описывать тот же разбор,
// что на экране. Включаем их вместе.
const AGENT_METHODS: ApiMethod[] = ['insight', 'ask', 'trace', 'analyze'];

function createHybridApi(http: Api, mock: Api, live: Set<ApiMethod> | 'all'): Api {
  if (live === 'all') return http;
  const agentLive = AGENT_METHODS.some((m) => live.has(m));
  const pick = <K extends ApiMethod>(key: K): Api[K] =>
    live.has(key) || (agentLive && AGENT_METHODS.includes(key)) ? http[key] : mock[key];
  return {
    personas: pick('personas'),
    briefing: pick('briefing'),
    insight: pick('insight'),
    feedback: pick('feedback'),
    exposureMap: pick('exposureMap'),
    weekly: pick('weekly'),
    health: pick('health'),
    ask: pick('ask'),
    trace: pick('trace'),
    analyze: pick('analyze'),
    company: live.has('company')
      ? async (id, signal) => {
          const real = await http.company(id, signal);
          // Тестовые разборы ссылаются на свои признаки (feat:group_loans…), которых нет в профиле API —
          // дописываем их с пометкой, чтобы ссылки раскрывались и не путались с данными API.
          const extra = await mock.company(id, signal).catch(() => null);
          if (!extra) return real;
          const have = new Set(real.features.map((f) => f.id));
          const marked = extra.features
            .filter((f) => !have.has(f.id))
            .map((f) => ({ ...f, label: `${f.label} (тестовые данные)` }));
          return { ...real, features: [...real.features, ...marked] };
        }
      : mock.company,
  };
}

const apiUrl = import.meta.env.VITE_API_URL as string | undefined;
const liveSetting = ((import.meta.env.VITE_API_LIVE as string | undefined) ?? 'personas,company,health').trim();
const live: Set<ApiMethod> | 'all' =
  liveSetting === 'all' ? 'all' : new Set(liveSetting.split(',').map((s) => s.trim()) as ApiMethod[]);

/** Откуда данные: только тестовые, часть из API или всё из API. */
export const dataMode: 'mock' | 'hybrid' | 'live' = !apiUrl ? 'mock' : live === 'all' ? 'live' : 'hybrid';

/** Пустой VITE_API_URL — работаем на встроенных тестовых данных. */
export const usingMocks = dataMode === 'mock';

/** Какие методы идут в настоящий API — для подписи об источнике данных. */
const ALL_METHODS: ApiMethod[] = [
  'personas', 'company', 'briefing', 'insight', 'exposureMap', 'weekly', 'ask', 'trace', 'analyze', 'feedback', 'health',
];

export const liveMethods: ApiMethod[] =
  dataMode === 'mock'
    ? []
    : live === 'all'
      ? ALL_METHODS
      : ALL_METHODS.filter((m) => live.has(m) || (AGENT_METHODS.includes(m) && AGENT_METHODS.some((a) => live.has(a))));

export const api: Api = apiUrl ? createHybridApi(createHttpApi(apiUrl), mockApi, live) : mockApi;
