import { api } from '../api/client';
import { useCurrentUser } from './session';
import { useAsync } from './useAsync';

/** Сколько событий в блоке «Главное» и на плашке главной — одни и те же, в одном порядке. */
export const TOP_EVENTS = 3;

export function useBriefing() {
  const { persona } = useCurrentUser();
  return useAsync((signal) => api.briefing(persona.id, signal), persona.id);
}
