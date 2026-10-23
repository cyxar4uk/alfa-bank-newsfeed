import { api } from '../api/client';
import type { Briefing } from '../api/types';
import { useCurrentUser } from './session';
import { useAsync } from './useAsync';

/** Сколько событий в блоке «Главное» и на плашке главной — одни и те же, в одном порядке. */
export const TOP_EVENTS = 3;

const TTL_MS = 60_000;

// Плашка на главной и брифинг читают один и тот же ответ: иначе при недетерминированном ранжировании
// на сервере они могли бы разойтись.
const cache = new Map<string, { at: number; promise: Promise<Briefing> }>();

function loadBriefing(personaId: string): Promise<Briefing> {
  const hit = cache.get(personaId);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise;
  const promise = api.briefing(personaId);
  cache.set(personaId, { at: Date.now(), promise });
  // После ошибки «Повторить» должен идти в сеть, а не в кэш.
  promise.catch(() => cache.delete(personaId));
  return promise;
}

export function useBriefing() {
  const { persona } = useCurrentUser();
  return useAsync(() => loadBriefing(persona.id), persona.id);
}
