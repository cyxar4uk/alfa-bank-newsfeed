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

function createHttpApi(baseUrl: string): Api {
  const base = baseUrl.replace(/\/$/, '');

  async function request<T>(path: string, init: RequestInit = {}): Promise<T | undefined> {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), TIMEOUT_MS);
    const outer = init.signal;
    const onOuterAbort = () => timeout.abort();
    outer?.addEventListener('abort', onOuterAbort);

    let res: Response;
    try {
      res = await fetch(`${base}${path}`, { ...init, signal: timeout.signal });
    } catch (e) {
      if (outer?.aborted) throw e;
      throw new ApiError(0, timeout.signal.aborted ? 'Сервер не ответил за 45 секунд' : 'Сервер не отвечает');
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener('abort', onOuterAbort);
    }

    if (!res.ok) throw new ApiError(res.status, `Сервер вернул ошибку ${res.status}`);
    const text = await res.text();
    if (!text) return undefined;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError(res.status, 'Сервер вернул ответ не в формате JSON');
    }
  }

  async function required<T>(path: string, signal?: AbortSignal): Promise<T> {
    const body = await request<T>(path, { signal });
    if (body === undefined) throw new ApiError(0, 'Сервер вернул пустой ответ');
    return body;
  }

  const q = encodeURIComponent;

  return {
    personas: (signal) => required(`/api/personas`, signal),
    company: (id, signal) => required(`/api/companies/${q(id)}`, signal),
    briefing: async (personaId, signal) => {
      // Принимаем и брифинг целиком, и голый список событий.
      const body = await required<Briefing | FeedItem[] | { items: FeedItem[] }>(
        `/api/briefing?persona=${q(personaId)}`,
        signal,
      );
      if (Array.isArray(body)) return { persona_id: personaId, summary: [], items: body };
      return { persona_id: personaId, summary: [], ...body };
    },
    // 204 — событие не касается компании пользователя.
    insight: async (eventId, personaId, signal) =>
      (await request<Insight>(`/api/insights/${q(eventId)}?persona=${q(personaId)}`, { signal })) ?? null,
    feedback: async (body) => {
      await request(`/api/feedback`, {
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
