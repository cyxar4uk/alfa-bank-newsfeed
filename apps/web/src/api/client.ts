import type { Briefing, CompanyProfile, FeedItem, Feedback, Insight, Persona } from './types';
import { mockApi } from '../mocks/mockApi';

export interface Api {
  personas(signal?: AbortSignal): Promise<Persona[]>;
  company(id: string, signal?: AbortSignal): Promise<CompanyProfile>;
  /** брифинг: сводка и события по убыванию значимости для пользователя */
  briefing(personaId: string, signal?: AbortSignal): Promise<Briefing>;
  /** null — событие не касается компании пользователя */
  insight(eventId: string, personaId: string, signal?: AbortSignal): Promise<Insight | null>;
  feedback(body: Feedback): Promise<void>;
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
    feedback: async (body) => {
      await request<unknown>(`/api/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    },
  };
}

const apiUrl = import.meta.env.VITE_API_URL as string | undefined;

/** Пустой VITE_API_URL — работаем на встроенных тестовых данных. */
export const usingMocks = !apiUrl;

export const api: Api = apiUrl ? createHttpApi(apiUrl) : mockApi;
