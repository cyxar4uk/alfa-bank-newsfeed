import { api } from '../api/client';
import type { Briefing } from '../api/types';
import { useCurrentUser } from './session';
import { useAsync } from './useAsync';

/** Сколько событий в блоке «Главное» и на плашке главной — одни и те же, в одном порядке. */
export const TOP_EVENTS = 3;

export type Period = 'day' | 'week';

const TTL_MS = 60_000;

// Плашка на главной и брифинг читают один и тот же ответ: иначе при недетерминированном ранжировании
// на сервере они могли бы разойтись.
const cache = new Map<string, { at: number; promise: Promise<Briefing> }>();

function loadBriefing(personaId: string, period: Period): Promise<Briefing> {
  const key = `${personaId}|${period}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise;
  const promise = api.briefing(personaId, undefined, period === 'week' ? 'week' : undefined);
  cache.set(key, { at: Date.now(), promise });
  // После ошибки «Повторить» должен идти в сеть, а не в кэш.
  promise.catch(() => cache.delete(key));
  return promise;
}

export function useBriefing(period: Period = 'day') {
  const { persona } = useCurrentUser();
  return useAsync(() => loadBriefing(persona.id, period), `${persona.id}|${period}`);
}

/** Брифинг за неделю — только когда он на экране: иначе лишний запрос на каждый заход в ленту. */
export function useWeekBriefing(enabled: boolean) {
  const { persona } = useCurrentUser();
  return useAsync(
    () => (enabled ? loadBriefing(persona.id, 'week') : Promise.resolve(null)),
    `${persona.id}|week|${enabled}`,
  );
}
