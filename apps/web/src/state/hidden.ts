import { useCallback, useSyncExternalStore } from 'react';
import { useSession } from './session';

// Скрытые пользователем инсайты: свои для каждой учётки и её пользователя (компания + роль), хранятся в браузере.
// Скрытое пропадает из брифинга и с плашки на главной; вернуть можно из брифинга.

const PREFIX = 'pulse.hidden.';
const listeners = new Set<() => void>();
const cache = new Map<string, string[]>();
const EMPTY: string[] = [];

function read(owner: string): string[] {
  const hit = cache.get(owner);
  if (hit) return hit;
  let ids: string[] = [];
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(PREFIX + owner) ?? '[]');
    ids = Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [];
  } catch {
    ids = [];
  }
  cache.set(owner, ids);
  return ids;
}

function write(owner: string, ids: string[]) {
  cache.set(owner, ids);
  try {
    localStorage.setItem(PREFIX + owner, JSON.stringify(ids));
  } catch {
    // без хранилища скрытое живёт до перезагрузки
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  // Другая вкладка скрыла или вернула событие — перечитываем хранилище.
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key.startsWith(PREFIX)) {
      cache.clear();
      listener();
    }
  };
  listeners.add(listener);
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

/** Скрытые события текущей учётки и пользователя. */
export function useHidden() {
  const { account, persona } = useSession();
  const owner = account && persona ? `${account.login}.${persona.id}` : null;
  const hidden = useSyncExternalStore(subscribe, () => (owner ? read(owner) : EMPTY));
  const hide = useCallback(
    (eventId: string) => {
      if (!owner) return;
      const ids = read(owner);
      if (!ids.includes(eventId)) write(owner, [...ids, eventId]);
    },
    [owner],
  );
  const unhide = useCallback(
    (eventId: string) => {
      if (owner) write(owner, read(owner).filter((id) => id !== eventId));
    },
    [owner],
  );
  const unhideAll = useCallback(() => {
    if (owner) write(owner, []);
  }, [owner]);
  return { hidden, hide, unhide, unhideAll };
}
