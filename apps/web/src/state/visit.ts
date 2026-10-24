// Дата прошлого визита в ленту — для «С 22 октября: …» и точки «новое». Своя для каждого пользователя.
// Читаем один раз за загрузку страницы и сразу записываем сегодняшнюю: повторные рендеры не сдвигают дату.
const key = (personaId: string) => `pulse.visit.${personaId}`;
const previous = new Map<string, string | null>();

export function lastVisit(personaId: string): string | null {
  if (!previous.has(personaId)) {
    let prev: string | null = null;
    try {
      prev = localStorage.getItem(key(personaId));
      const d = new Date();
      const local = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      localStorage.setItem(key(personaId), local);
    } catch {
      // без хранилища каждый визит — первый
    }
    previous.set(personaId, prev);
  }
  return previous.get(personaId) ?? null;
}
