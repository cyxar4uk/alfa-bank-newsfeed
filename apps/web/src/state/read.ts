// Прочитанные события: своя отметка у каждого пользователя, хранится в браузере. Для прототипа этого достаточно.
const key = (personaId: string) => `pulse.read.${personaId}`;

export function readEvents(personaId: string): Set<string> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key(personaId)) ?? '[]');
    return new Set(Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}

export function markRead(personaId: string, eventId: string) {
  const ids = readEvents(personaId);
  if (ids.has(eventId)) return;
  ids.add(eventId);
  try {
    // последние 500 — чтобы хранилище не росло без конца
    localStorage.setItem(key(personaId), JSON.stringify([...ids].slice(-500)));
  } catch {
    // без хранилища отметка живёт до перезагрузки — не страшно
  }
}
