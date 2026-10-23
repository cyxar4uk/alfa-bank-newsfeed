// Имитация API на тестовых данных. Задержки — чтобы были видны состояния загрузки.
// Параметр адреса включает состояние для проверки: ?mock=empty — пустой брифинг, ?mock=error — ошибка везде,
// ?mock=error-briefing или ?mock=error-insight — ошибка только брифинга или разбора. Режим запоминается до
// закрытия вкладки, чтобы переживать переходы; ?mock=off его сбрасывает.
import type { Api } from '../api/client';
import type { Briefing, FeedItem, Insight, Statement } from '../api/types';
import { companies, details, events, feeds, personas, RANK_SCORES, sources, summaries } from './data';

const MODE_KEY = 'pulse.mock';

function readMode(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get('mock');
  try {
    if (fromUrl === 'off') sessionStorage.removeItem(MODE_KEY);
    else if (fromUrl) sessionStorage.setItem(MODE_KEY, fromUrl);
    return fromUrl === 'off' ? null : (fromUrl ?? sessionStorage.getItem(MODE_KEY));
  } catch {
    return fromUrl === 'off' ? null : fromUrl;
  }
}

const mode = readMode();

function wait(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new DOMException('Запрос отменён', 'AbortError'));
    });
  });
}

async function respond<T>(ms: number, value: () => T, scope: string, signal?: AbortSignal): Promise<T> {
  await wait(ms, signal);
  if (mode === 'error' || mode === `error-${scope}`) throw new Error('Тестовая ошибка сервера');
  return value();
}

function findPersona(id: string) {
  const persona = personas.find((p) => p.id === id);
  if (!persona) throw new Error(`Нет пользователя ${id}`);
  return persona;
}

function feedItems(personaId: string): FeedItem[] {
  return (feeds[personaId] ?? []).map((entry, i) => {
    const event = events.find((e) => e.id === entry.event);
    if (!event) throw new Error(`Нет события ${entry.event}`);
    const source = sources[event.primary];
    return {
      event_id: event.id,
      event: { title: event.title, date: event.date },
      relevance: {
        score: RANK_SCORES[i] ?? 0.4,
        reason: entry.reason,
        refs: entry.refs,
        breakdown: details[`${event.id}|${personaId}`]?.breakdown,
      },
      has_bank_view: event.bank.length > 0,
      source: {
        id: source.id,
        kind: source.kind,
        title: source.title,
        publisher: source.publisher,
        url: source.url,
        published_at: source.published_at,
      },
      factors: entry.factors,
      channel: entry.channel,
      channel_text: entry.channel_text,
    };
  });
}

function collectRefs(statements: Statement[], extra: string[]): Set<string> {
  return new Set([...statements.flatMap((s) => s.refs), ...extra]);
}

export const mockApi: Api = {
  personas: (signal) => respond(300, () => personas, 'personas', signal),

  company: (id, signal) =>
    respond(
      200,
      () => {
        const company = companies.find((c) => c.id === id);
        if (!company) throw new Error(`Нет компании ${id}`);
        return company;
      },
      'company',
      signal,
    ),

  briefing: (personaId, signal) =>
    respond(
      700,
      (): Briefing => {
        findPersona(personaId);
        if (mode === 'empty') return { persona_id: personaId, summary: [], items: [] };
        const summary = summaries[personaId] ?? [];
        const refs = collectRefs(summary, []);
        return {
          persona_id: personaId,
          summary,
          sources: [...refs].filter((r) => r.startsWith('src:')).map((r) => sources[r]),
          items: feedItems(personaId),
        };
      },
      'briefing',
      signal,
    ),

  insight: (eventId, personaId, signal) =>
    respond(
      3200,
      (): Insight | null => {
        findPersona(personaId);
        const item = feedItems(personaId).find((i) => i.event_id === eventId);
        const event = events.find((e) => e.id === eventId);
        if (!item || !event) return null;
        const detail = details[`${eventId}|${personaId}`];

        const why = detail?.why ?? [{ text: item.relevance.reason, origin: 'ai', refs: item.relevance.refs, confidence: 'medium' } satisfies Statement];
        const risks = detail?.risks ?? [];
        const opportunities = detail?.opportunities ?? [];
        const factors = detail?.factors ?? [];
        const actions = detail?.actions ?? [];
        const vsMarket = detail?.bank_vs_market;
        const estimateBases = detail?.estimates?.flatMap((e) => e.scenarios.map((s) => s.basis)) ?? [];

        const refs = collectRefs(
          [
            ...event.what,
            ...why,
            ...risks,
            ...opportunities,
            ...factors,
            ...event.bank,
            ...(vsMarket ? [vsMarket.bank, ...(vsMarket.market ? [vsMarket.market] : [])] : []),
            ...estimateBases,
          ],
          [...actions.flatMap((a) => a.refs), ...item.relevance.refs],
        );

        return {
          id: `ins:${eventId}:${personaId}`,
          event: item.event,
          relevance: item.relevance,
          what_happened: event.what,
          why_it_matters: why,
          consequences: { risks, opportunities, factors },
          bank_view: event.bank,
          actions,
          sources: [...refs].filter((r) => r.startsWith('src:')).map((r) => sources[r]),
          features_used: [...refs].filter((r) => r.startsWith('feat:')),
          quality: {
            // Тестовые данные агентом не проверялись — проверок не показываем.
            checks_passed: [],
            warnings: detail?.warnings ?? [
              'Тестовые данные: подробный разбор подготовлен только для эталонных пар; здесь факты, позиция банка и связь с компанией',
            ],
          },
          trace_id: `tr:${eventId}:${personaId}`,
          exposure: detail?.exposure ?? {
            channels: [{ kind: item.channel, factor: item.factors[0], text: item.channel_text, counterparties: [] }],
            gaps: [],
          },
          group_impact: detail?.group_impact ?? null,
          bank_vs_market: vsMarket ?? null,
          estimates: detail?.estimates ?? [],
        };
      },
      'insight',
      signal,
    ),

  feedback: () => respond(300, () => undefined, 'feedback'),
};
