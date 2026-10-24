// Имитация API на тестовых данных. Задержки — чтобы были видны состояния загрузки.
// Параметр адреса включает состояние для проверки: ?mock=empty — пустой брифинг, ?mock=error — ошибка везде,
// ?mock=error-briefing, error-insight, error-map, error-weekly — ошибка только одного экрана. Режим запоминается до
// закрытия вкладки, чтобы переживать переходы; ?mock=off его сбрасывает.
import type { Api } from '../api/client';
import type { Action, Briefing, FactorRef, FeedItem, Insight, Statement, WeeklySummary } from '../api/types';
import { companies, details, events, exposureMaps, feeds, personas, RANK_SCORES, sources, summaries } from './data';

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

function sourcesOf(refs: Set<string>) {
  return [...refs].filter((r) => r.startsWith('src:')).map((r) => sources[r]);
}

/** Сводка недели из брифинга: события по факторам, позиция банка и шаги из разборов. */
function buildWeekly(personaId: string): WeeklySummary {
  const items = feedItems(personaId);
  const sections = new Map<string, { factor: FactorRef; statements: Statement[] }>();
  const bankView: Statement[] = [];
  const actions: Action[] = [];
  for (const item of items) {
    const event = events.find((e) => e.id === item.event_id);
    if (!event) continue;
    const factor = item.factors[0] ?? { code: 'other', label: 'Другое' };
    const section = sections.get(factor.code) ?? { factor, statements: [] };
    const detail = details[`${event.id}|${personaId}`];
    const why = detail?.why.filter((w) => w.origin === 'ai').at(-1) ?? {
      text: item.relevance.reason,
      origin: 'ai',
      refs: item.relevance.refs,
      confidence: 'medium',
    };
    section.statements.push(...event.what.slice(0, 1), why);
    sections.set(factor.code, section);
    for (const b of event.bank.slice(0, 1)) if (!bankView.some((x) => x.text === b.text)) bankView.push(b);
    for (const a of detail?.actions ?? []) if (a.kind !== 'product' && !actions.some((x) => x.text === a.text)) actions.push(a);
  }
  const all = [...[...sections.values()].flatMap((x) => x.statements), ...bankView];
  const dates = items.map((i) => i.event.date).sort();
  return {
    persona_id: personaId,
    period: { from: dates[0] ?? '', to: dates[dates.length - 1] ?? '' },
    sections: [...sections.values()],
    bank_view: bankView,
    actions,
    sources: sourcesOf(collectRefs(all, actions.flatMap((a) => a.refs))),
  };
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

  exposureMap: (companyId, signal) =>
    respond(
      600,
      () => {
        const map = exposureMaps[companyId];
        if (!map) throw new Error(`Нет карты для компании ${companyId}`);
        if (mode === 'empty') return { ...map, factors: [] };
        const refs = collectRefs(map.factors.flatMap((f) => f.evidence), []);
        return { ...map, sources: sourcesOf(refs) };
      },
      'map',
      signal,
    ),

  weekly: (personaId, signal) =>
    respond(
      700,
      () => {
        findPersona(personaId);
        if (mode === 'empty') return { persona_id: personaId, period: { from: '', to: '' }, sections: [], bank_view: [], actions: [] };
        return buildWeekly(personaId);
      },
      'weekly',
      signal,
    ),

  feedback: () => respond(300, () => undefined, 'feedback'),
};
