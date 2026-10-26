import type {
  AnalyzeRequest,
  AskAnswer,
  Briefing,
  CatalogSource,
  CompanyExposure,
  EventDetail,
  CompanyProfile,
  ExposureMap,
  FeedItem,
  Feedback,
  Health,
  Insight,
  InsightResult,
  JobStatus,
  Persona,
  PersonaInputs,
  Role,
  SourceConnection,
  RiskFactor,
  RiskMap,
  RiskStrength,
  SensitivityFactor,
  Statement,
  Story,
  Strength,
  Trace,
  WeeklySummary,
} from './types';
import { scrubDeep } from '../state/trace';

export interface Api {
  personas(signal?: AbortSignal): Promise<Persona[]>;
  company(id: string, signal?: AbortSignal): Promise<CompanyProfile>;
  /** брифинг: сводка и события по убыванию значимости для пользователя; week — сюжеты недели */
  briefing(personaId: string, signal?: AbortSignal, period?: 'week'): Promise<Briefing>;
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

/** Методы настоящего API, которых нет в тестовых данных: фоновая сборка разбора и карта в формате API. */
export interface LiveApi extends Api {
  /** карта чувствительности как её отдаёт API — с доказательствами из данных банка */
  exposure(companyId: string, signal?: AbortSignal): Promise<CompanyExposure>;
  /** разбор без ожидания: готовый, статус фоновой сборки или «не касается» */
  insightJob(eventId: string, personaId: string, signal?: AbortSignal): Promise<InsightResult>;
  /** статус фоновой сборки разбора */
  insightStatus(eventId: string, personaId: string, signal?: AbortSignal): Promise<JobStatus>;
  /** своя новость без ожидания: готовый разбор, статус сборки (по его event_id опрашиваем) или «не касается» */
  analyzeJob(body: AnalyzeRequest, signal?: AbortSignal): Promise<InsightResult>;
  /** готовый разбор только из кэша (cached=true): null — не собран, сборку не запускает */
  cachedInsight(eventId: string, personaId: string, signal?: AbortSignal): Promise<Insight | null>;
  /** новость целиком; null — метода или текста нет */
  eventDetail(eventId: string, signal?: AbortSignal): Promise<EventDetail | null>;
  /** поиск событий в формате ленты; null — поиска в API нет, ищем по ленте */
  search(query: string, personaId: string, signal?: AbortSignal): Promise<Briefing | null>;
  /** каталог источников; null — каталога в API пока нет */
  catalog(personaId: string, signal?: AbortSignal): Promise<CatalogSource[] | null>;
  /** «По этой теме»: события, связанные с этим, в формате ленты; null — метода в API пока нет */
  related(eventId: string, personaId: string, signal?: AbortSignal): Promise<FeedItem[] | null>;
  /** отметить источник подключённым; ответ — что произошло (null — сервер не объяснил) */
  connectSource(id: string, personaId: string): Promise<SourceConnection | null>;
  /** сохранённые «мои числа»; null — метода в API пока нет или ничего не сохранено */
  inputs(personaId: string, signal?: AbortSignal): Promise<PersonaInputs | null>;
  /** сохранить «мои числа»; false — метода в API пока нет; partial — сохранено без валютной выручки */
  saveInputs(personaId: string, body: PersonaInputs): Promise<boolean | 'partial'>;
  /** отключить источник; null — у API такого метода пока нет, отключение только на экране */
  disconnectSource(id: string, personaId: string): Promise<SourceConnection | null>;
  /** «К чему уязвима компания» глазами роли; null — метода в API пока нет */
  riskMap(companyId: string, personaId: string, role: Role, signal?: AbortSignal): Promise<RiskMap | null>;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Лента с дооценкой моделью считается до минуты — ждём с запасом.
const TIMEOUT_MS = 90_000;

const asArray = <T>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

/** Брифинг принимаем целиком или голым списком событий; отсутствующие поля заменяем пустыми. */
function normalizeBriefing(personaId: string, raw: unknown): Briefing {
  const body = (Array.isArray(raw) ? { items: raw } : (raw ?? {})) as Partial<Briefing>;
  return {
    persona_id: personaId,
    summary: asArray(body.summary),
    sources: asArray(body.sources),
    items: asArray<FeedItem>(body.items).map((item) => ({ ...item, factors: asArray(item.factors) })),
    candidates: typeof body.candidates === 'number' ? body.candidates : undefined,
    period: body.period === 'week' ? 'week' : 'day',
    week: asArray<unknown>(body.week).filter((d): d is string => typeof d === 'string'),
    stories: asArray<Story>(body.stories)
      .filter((st) => st && st.title)
      .map((st) => ({ ...st, daily_counts: counts(st.daily_counts), event_ids: asArray<string>(st.event_ids) })),
    bank: body.bank?.text ? body.bank : null,
    action: body.action?.label ? body.action : null,
  };
}

/** Счётчики по дням: только неотрицательные числа, всё прочее — ноль. */
function counts(raw: unknown): number[] {
  return asArray<unknown>(raw).map((n) => (typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : 0));
}

const RISK_STRENGTH: Record<string, RiskStrength> = {
  strong: 'strong',
  high: 'strong',
  notable: 'notable',
  medium: 'notable',
  weak: 'weak',
  low: 'weak',
};

/** Карта уязвимости: неизвестную силу считаем слабой, пустые поля — пустыми, «ограничения» строкой или списком. */
function normalizeRiskMap(companyId: string, role: Role, raw: unknown): RiskMap {
  const body = (raw ?? {}) as Partial<RiskMap> & { limits?: unknown };
  const limits = typeof body.limits === 'string' ? [body.limits] : asArray<unknown>(body.limits).filter((x): x is string => typeof x === 'string');
  return {
    company_id: body.company_id ?? companyId,
    role: body.role ?? role,
    week: asArray<unknown>(body.week).filter((d): d is string => typeof d === 'string'),
    factors: asArray<Partial<RiskFactor> & { strength?: string }>(body.factors)
      .filter((f) => f.code && f.label)
      .map((f) => {
        const week = counts(f.week_counts);
        return {
          code: f.code as string,
          label: f.label as string,
          strength: RISK_STRENGTH[f.strength ?? ''] ?? 'weak',
          why: f.why ?? '',
          is_estimate: f.is_estimate === true,
          now: f.now?.title && f.now.event_id ? f.now : null,
          bank: f.bank?.text ? f.bank : null,
          week_counts: week,
          news_count: typeof f.news_count === 'number' ? f.news_count : week.reduce((a, b) => a + b, 0),
        };
      }),
    limits: limits.filter((x) => x.trim()),
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

function createHttpApi(baseUrl: string): LiveApi {
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
        throw new ApiError(0, timeout.signal.aborted ? 'Сервер не ответил за 90 секунд' : 'Сервер не отвечает');
      }
      if (!res.ok) {
        // Причину сервер пишет в detail (FastAPI): «событие не найдено», «бюджет на сегодня исчерпан …».
        let detail = '';
        try {
          const parsed = JSON.parse(text) as { detail?: unknown };
          if (typeof parsed.detail === 'string') detail = parsed.detail;
        } catch {
          // тело не JSON — остаётся код
        }
        throw new ApiError(res.status, detail || `Сервер вернул ошибку ${res.status}`);
      }
      if (res.status === 204) return { status: 204 };
      if (!text) {
        // Для POST пустое тело — нормальный ответ «принято».
        if (init.method === 'POST') return { status: res.status };
        throw new ApiError(res.status, 'Сервер вернул пустой ответ');
      }
      try {
        // Служебные id компаний («U_4909», «Компания №92457») пользователю не показываем — убираем из текстов разом.
        return { status: res.status, body: scrubDeep(JSON.parse(text)) as T };
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

  /** Новые методы API (07_feedback §3) могут быть ещё не выкачены: 404/405 и пустой ответ — это «нет», а не ошибка. */
  async function missingAsNull<T>(call: Promise<{ status: number; body?: T }>): Promise<T | null> {
    try {
      const { body } = await call;
      return body ?? null;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return null;
      throw e;
    }
  }

  return {
    personas: (signal) => required(`/api/personas`, signal),
    company: (id, signal) => required(`/api/companies/${q(id)}`, signal),
    briefing: async (personaId, signal, period) =>
      normalizeBriefing(
        personaId,
        await required<unknown>(`/api/briefing?persona=${q(personaId)}${period ? `&period=${period}` : ''}`, signal),
      ),
    // 204 — событие не касается компании пользователя.
    insight: async (eventId, personaId, signal) => {
      const { body } = await request<Insight>(`/api/insights/${q(eventId)}?persona=${q(personaId)}`, { signal });
      return body ?? null;
    },
    exposure: (companyId, signal) => required(`/api/companies/${q(companyId)}/exposure`, signal),
    insightJob: async (eventId, personaId, signal) => {
      const { status, body } = await request<Insight | JobStatus>(
        `/api/insights/${q(eventId)}?persona=${q(personaId)}&wait=false`,
        { signal },
      );
      if (status === 204 || !body) return { kind: 'none' };
      return status === 202 ? { kind: 'building', job: body as JobStatus } : { kind: 'ready', insight: body as Insight };
    },
    analyzeJob: async (req, signal) => {
      const { status, body } = await request<Insight | JobStatus>(`/api/analyze?wait=false`, { ...post(req), signal });
      if (status === 204 || !body) return { kind: 'none' };
      return status === 202 ? { kind: 'building', job: body as JobStatus } : { kind: 'ready', insight: body as Insight };
    },
    cachedInsight: async (eventId, personaId, signal) => {
      const { body } = await request<Insight>(`/api/insights/${q(eventId)}?persona=${q(personaId)}&cached=true`, { signal });
      return body ?? null;
    },
    eventDetail: (eventId, signal) => missingAsNull(request<EventDetail>(`/api/events/${q(eventId)}`, { signal })),
    search: async (query, personaId, signal) => {
      const body = await missingAsNull(request<unknown>(`/api/search?q=${q(query)}&persona=${q(personaId)}`, { signal }));
      return body === null ? null : normalizeBriefing(personaId, body);
    },
    catalog: async (personaId, signal) => {
      const body = await missingAsNull(request<unknown>(`/api/sources/catalog?persona=${q(personaId)}`, { signal }));
      if (body === null) return null;
      // Поля «для вашей отрасли» и «что даст подключение» приходят под двумя именами — сводим к одному.
      return asArray<CatalogSource>(Array.isArray(body) ? body : (body as { items?: unknown }).items).map((s) => ({
        ...s,
        for_your_industry: s.for_your_industry ?? s.relevant ?? null,
        benefit: s.benefit ?? s.gives ?? null,
      }));
    },
    riskMap: async (companyId, personaId, role, signal) => {
      const body = await missingAsNull(request<unknown>(`/api/companies/${q(companyId)}/risk-map?persona=${q(personaId)}`, { signal }));
      return body === null ? null : normalizeRiskMap(companyId, role, body);
    },
    related: async (eventId, personaId, signal) => {
      const body = await missingAsNull(request<unknown>(`/api/events/${q(eventId)}/related?persona=${q(personaId)}`, { signal }));
      if (body === null) return null;
      // Только полные элементы: без заголовка, источника или оценки карточку не нарисовать — не роняем карточку события.
      const seen = new Set<string>();
      return normalizeBriefing(personaId, body).items.filter((i) => {
        const ok = !!i && !!i.event_id && !!i.event?.title && !!i.source && (!!i.takeaway?.level || !!i.relevance) && !seen.has(i.event_id);
        if (ok) seen.add(i.event_id);
        return ok;
      });
    },
    connectSource: async (id, personaId) => {
      const { body } = await request<SourceConnection>(`/api/sources/${q(id)}/connect?persona=${q(personaId)}`, post({}));
      return body?.message ? body : null;
    },
    inputs: (personaId, signal) => missingAsNull(request<PersonaInputs>(`/api/personas/${q(personaId)}/inputs`, { signal })),
    saveInputs: async (personaId, body) => {
      try {
        // Пустые поля не отправляем: API принимает только заданные значения.
        const filled = Object.fromEntries(Object.entries(body).filter(([k, v]) => v != null && k !== 'updated_at'));
        const put = (payload: Record<string, unknown>) =>
          request<unknown>(`/api/personas/${q(personaId)}/inputs`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
        try {
          await put(filled);
        } catch (e) {
          // API ещё не знает валютную выручку (422 на лишнее поле) — сохраняем остальное, выручку агент получит вопросом
          if (!(e instanceof ApiError && e.status === 422 && 'fx_revenue_month_rub' in filled)) throw e;
          const { fx_revenue_month_rub: _skip, ...rest } = filled;
          void _skip;
          if (Object.keys(rest).length === 0) return false;
          await put(rest);
          return 'partial';
        }
        return true;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return false;
        throw e;
      }
    },
    disconnectSource: async (id, personaId) => {
      try {
        const { body } = await request<SourceConnection>(`/api/sources/${q(id)}/disconnect?persona=${q(personaId)}`, post({}));
        return body?.message ? body : { source: { id, name: id, country: 'ru', kind: 'free', connected: false }, message: '' };
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return null;
        throw e;
      }
    },
    insightStatus: (eventId, personaId, signal) =>
      required(`/api/insights/${q(eventId)}/status?persona=${q(personaId)}`, signal),
    exposureMap: async (companyId, signal) =>
      normalizeMap(await required<ExposureMap>(`/api/companies/${q(companyId)}/exposure`, signal)),
    weekly: async (personaId, signal) =>
      normalizeWeekly(personaId, await required<WeeklySummary>(`/api/weekly?persona=${q(personaId)}`, signal)),
    feedback: async (body) => {
      await request<unknown>(`/api/feedback`, post(body));
    },
    health: (signal) => required(`/api/health`, signal),
    ask: async (insightId, _personaId, question, signal) => {
      const { body } = await request<AskAnswer>(`/api/insights/${q(insightId)}/ask`, {
        ...post({ question }),
        signal,
      });
      if (!body) throw new ApiError(204, 'Сервер не вернул ответ');
      return {
        question,
        answer: asArray(body.answer),
        sources: asArray(body.sources),
        refusal: body.refusal ?? null,
        warnings: asArray(body.warnings),
      };
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


const apiUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

export const api: LiveApi = createHttpApi(apiUrl);
