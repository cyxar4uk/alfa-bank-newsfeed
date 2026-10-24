/** Кусок текста: обычный или цитата, на которую опирается вывод. */
export interface Segment {
  text: string;
  mark: boolean;
}

/** Разметить в тексте цитаты (точное совпадение без учёта регистра, не короче 12 знаков, без пересечений). */
export function highlight(text: string, quotes: string[]): Segment[] {
  const lower = text.toLowerCase();
  const marks = quotes
    .map((q) => q.trim())
    .filter((q) => q.length >= 12)
    .map((q) => {
      const at = lower.indexOf(q.toLowerCase());
      return at >= 0 ? { at, end: at + q.length } : null;
    })
    .filter((m): m is { at: number; end: number } => m !== null)
    .sort((a, b) => a.at - b.at);
  const out: Segment[] = [];
  let pos = 0;
  for (const m of marks) {
    if (m.at < pos) continue;
    if (m.at > pos) out.push({ text: text.slice(pos, m.at), mark: false });
    out.push({ text: text.slice(m.at, m.end), mark: true });
    pos = m.end;
  }
  if (pos < text.length) out.push({ text: text.slice(pos), mark: false });
  return out;
}
