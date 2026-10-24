// Имитация API на тестовых данных. Задержки — чтобы были видны состояния загрузки.
// Параметр адреса включает состояние для проверки: ?mock=empty — пустой брифинг, ?mock=error — ошибка везде,
// ?mock=error-briefing, error-insight, error-map, error-weekly — ошибка только одного экрана; ?mock=conflict — у первой
// гипотезы разбора помечено расхождение с позицией банка (в эталонах его нет — только для проверки интерфейса). Режим запоминается до
// закрытия вкладки, чтобы переживать переходы; ?mock=off его сбрасывает.
import type { Api } from '../api/client';
import type {
  Action,
  AskAnswer,
  Briefing,
  FactorRef,
  FeedItem,
  Insight,
  Source,
  Statement,
  Trace,
  TraceStep,
  WeeklySummary,
} from '../api/types';
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

/** ?mock=conflict: пометить первую гипотезу расхождением с первой позицией банка в разборе. */
function withTestConflict(insight: Insight | null): Insight | null {
  if (mode !== 'conflict' || !insight) return insight;
  const { risks, opportunities } = insight.consequences;
  const all = [...opportunities, ...risks];
  const target = all.find((s) => s.origin === 'ai' && s.confidence === 'low') ?? all.find((s) => s.origin === 'ai');
  const bankRefs = insight.bank_view[0]?.refs ?? [];
  if (!target || bankRefs.length === 0) return insight;
  const mark = (s: Statement): Statement =>
    s === target
      ? {
          ...s,
          bank_conflict: {
            text: 'тестовый сценарий для проверки интерфейса — в эталонных разборах такого расхождения нет',
            refs: bankRefs,
          },
        }
      : s;
  return {
    ...insight,
    consequences: { ...insight.consequences, risks: risks.map(mark), opportunities: opportunities.map(mark) },
  };
}

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

/** Разбор пары «событие × пользователь»; null — событие не касается компании пользователя. */
function buildInsight(eventId: string, personaId: string): Insight | null {
  const item = feedItems(personaId).find((i) => i.event_id === eventId);
  const event = events.find((e) => e.id === eventId);
  if (!item || !event) return null;
  const detail = details[`${eventId}|${personaId}`];

  const why = detail?.why ?? [
    { text: item.relevance.reason, origin: 'ai', refs: item.relevance.refs, confidence: 'medium' } satisfies Statement,
  ];
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
    sources: sourcesOf(refs),
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
}

/** id разбора и трассы в тестовых данных: ins:<событие>:<пользователь>, tr:<событие>:<пользователь> */
function parseIds(id: string): { eventId: string; personaId: string } | null {
  const [, eventId, personaId] = id.split(':');
  return eventId && personaId ? { eventId, personaId } : null;
}

const words = (text: string) => new Set(text.toLowerCase().match(/[а-яёa-z0-9]{4,}/g) ?? []);

/**
 * Ответ на уточняющий вопрос по тестовым данным: подбираем утверждения самого разбора по теме вопроса.
 * Нового знания мок не создаёт — это делает агент API.
 */
function answerQuestion(insight: Insight, question: string): Statement[] {
  const q = question.toLowerCase();
  const c = insight.consequences;
  if (/банк|альфа/.test(q) && insight.bank_view.length > 0) return insight.bank_view;
  if (/риск/.test(q) && c.risks.length > 0) return c.risks;
  if (/возможност/.test(q) && c.opportunities.length > 0) return c.opportunities;
  if (/контрагент|покупател|поставщик|через кого|групп/.test(q)) {
    const data = insight.why_it_matters.filter((s) => s.origin === 'data');
    if (data.length > 0) return data;
  }
  if (/сделать|шаг|действ/.test(q)) {
    const steps = insight.actions.filter((a) => a.kind !== 'product');
    if (steps.length > 0) {
      return steps.map((a) => ({ text: a.text, origin: 'ai', refs: a.refs, confidence: 'medium' }) satisfies Statement);
    }
  }
  if (/основан|источник|откуда/.test(q)) {
    return [...insight.what_happened, ...insight.why_it_matters.filter((s) => s.origin === 'data')];
  }
  // Иначе — утверждения с наибольшим совпадением слов с вопросом.
  const qw = words(question);
  const all = [...insight.what_happened, ...insight.why_it_matters, ...c.risks, ...c.opportunities, ...c.factors, ...insight.bank_view];
  const scored = all
    .map((s) => ({ s, n: [...words(s.text)].filter((w) => qw.has(w)).length }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n)
    .slice(0, 3)
    .map((x) => x.s);
  if (scored.length > 0) return scored;
  return [
    {
      text: 'В материалах разбора ответа на этот вопрос нет. Переформулируйте вопрос или откройте источники в блоке «На чём основано».',
      origin: 'ai',
      refs: [],
      confidence: 'low',
    },
  ];
}

/**
 * Трасса по тестовым данным: агент не запускался, шаги восстановлены по составу разбора (какие признаки
 * и источники в нём есть). Самопроверку агента не изображаем: показываем только, находятся ли ссылки.
 */
function buildTrace(insight: Insight, traceId: string): Trace {
  const news = insight.sources.filter((s) => s.kind === 'news').map((s) => s.id);
  const alfa = insight.sources.filter((s) => s.kind === 'alfa_analytics').map((s) => s.id);
  const known = new Set([...insight.sources.map((s) => s.id), ...insight.features_used]);
  const all = [
    ...insight.what_happened,
    ...insight.why_it_matters,
    ...insight.consequences.risks,
    ...insight.consequences.opportunities,
    ...insight.consequences.factors,
    ...insight.bank_view,
  ];
  const unresolved = [...new Set(all.flatMap((s) => s.refs))].filter((r) => !known.has(r));
  const unsourced = all.filter((s) => ['fact', 'bank', 'data'].includes(s.origin) && s.refs.length === 0);
  const linksOk = unresolved.length === 0 && unsourced.length === 0;
  const channels = insight.exposure?.channels.filter((c) => c.kind !== 'direct') ?? [];

  const steps: Omit<TraceStep, 'n'>[] = [
    {
      kind: 'plan',
      summary: `Нужны: профиль компании, новости по событию, аналитика банка${channels.length > 0 ? ', цепочка через контрагентов' : ''}`,
    },
    {
      kind: 'tool',
      tool: 'get_company_profile',
      summary: 'Признаки компании, которые повлияли на вывод',
      output_refs: insight.features_used,
    },
    { kind: 'tool', tool: 'search_news', summary: 'Новости по событию', output_refs: news },
    {
      kind: 'tool',
      tool: 'search_alfa_analytics',
      summary: alfa.length > 0 ? 'Материалы аналитиков банка по теме' : 'Материалов банка по теме не найдено',
      output_refs: alfa,
    },
    ...(channels.length > 0
      ? [{ kind: 'tool' as const, tool: 'get_counterparty_chain', summary: channels.map((c) => c.text).join('; '), output_refs: [] }]
      : []),
    { kind: 'llm', purpose: 'черновик разбора по схеме', summary: 'Модель и расход в тестовом режиме не записываются' },
    {
      kind: 'check',
      verdict: null,
      summary: linksOk
        ? 'Самопроверка агентом не выполнялась. Ссылки утверждений находятся в источниках и признаках разбора'
        : `Самопроверка агентом не выполнялась. Не найдены ссылки: ${[...unresolved, ...unsourced.map((s) => s.text.slice(0, 40))].join(', ')}`,
    },
  ];
  return {
    id: traceId,
    insight_id: insight.id,
    steps: steps.map((s, i) => ({ n: i + 1, ...s })),
    sources: insight.sources,
    features_used: insight.features_used,
    note: 'Тестовые данные: агент не запускался, шаги восстановлены по составу разбора',
  };
}

/**
 * Своя новость в тестовом режиме: разобрать её может только агент API — показываем сам материал
 * и честно об этом говорим.
 */
function analyzeOwn(personaId: string, url: string | undefined, text: string | undefined): Insight {
  const body = (text ?? '').trim();
  const firstSentences = body.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ');
  const title = (firstSentences || url || 'Ваш материал').slice(0, 140);
  const source: Source = {
    id: 'src:user:own',
    kind: 'news',
    title,
    publisher: 'Ваш материал',
    url: url ?? '',
    published_at: null,
    fragment: body ? body.slice(0, 600) : undefined,
  };
  return {
    id: `ins:own:${personaId}`,
    event: { title, date: new Date().toISOString().slice(0, 10) },
    relevance: { score: 0, reason: 'Значимость для компании оценивает агент — в тестовом режиме он не подключён', refs: [] },
    what_happened: body ? [{ text: firstSentences, origin: 'fact', refs: [source.id], confidence: 'high' }] : [],
    why_it_matters: [],
    consequences: { risks: [], opportunities: [], factors: [] },
    bank_view: [],
    actions: [],
    sources: [source],
    features_used: [],
    quality: {
      checks_passed: [],
      warnings: [
        'Тестовый режим: разбор своей новости делает агент API. Без него показан только сам материал — связи с компанией, рисков и позиции банка нет.',
      ],
    },
    trace_id: null,
    exposure: null,
  };
}

const emptyWeekly = (personaId: string): WeeklySummary => ({
  persona_id: personaId,
  period: { from: '', to: '' },
  sections: [],
  bank_view: [],
  actions: [],
});

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

  // Пользователь без тестовых данных (например, из настоящего API) получает пустые ответы, а не ошибку.
  briefing: (personaId, signal) =>
    respond(
      700,
      (): Briefing => {
        if (mode === 'empty') return { persona_id: personaId, summary: [], items: [] };
        const summary = summaries[personaId] ?? [];
        return {
          persona_id: personaId,
          summary,
          sources: sourcesOf(collectRefs(summary, [])),
          items: feedItems(personaId),
        };
      },
      'briefing',
      signal,
    ),

  insight: (eventId, personaId, signal) =>
    respond(3200, () => withTestConflict(buildInsight(eventId, personaId)), 'insight', signal),

  exposureMap: (companyId, signal) =>
    respond(
      600,
      () => {
        const map = exposureMaps[companyId];
        if (!map || mode === 'empty') return { company_id: companyId, factors: [], sources: [], position: map?.position ?? null };
        return { ...map, sources: sourcesOf(collectRefs(map.factors.flatMap((f) => f.evidence), [])) };
      },
      'map',
      signal,
    ),

  weekly: (personaId, signal) =>
    respond(700, () => (mode === 'empty' ? emptyWeekly(personaId) : buildWeekly(personaId)), 'weekly', signal),

  feedback: () => respond(300, () => undefined, 'feedback'),

  health: (signal) => respond(100, () => ({ status: 'ok' as const, db: 'ok' as const, data: [] }), 'health', signal),

  ask: (insightId, _personaId, question, signal) =>
    respond(
      1500,
      (): AskAnswer => {
        const ids = parseIds(insightId);
        const insight = ids ? buildInsight(ids.eventId, ids.personaId) : null;
        const answer: Statement[] = insight
          ? answerQuestion(insight, question)
          : [{ text: 'Для этого разбора уточняющие вопросы работают только с агентом API.', origin: 'ai', refs: [], confidence: 'low' }];
        return { question, answer, sources: sourcesOf(collectRefs(answer, [])) };
      },
      'ask',
      signal,
    ),

  trace: (traceId, signal) =>
    respond(
      800,
      () => {
        const ids = parseIds(traceId);
        const insight = ids ? buildInsight(ids.eventId, ids.personaId) : null;
        return insight ? buildTrace(insight, traceId) : null;
      },
      'trace',
      signal,
    ),

  analyze: (req, signal) => respond(2500, () => analyzeOwn(req.persona_id, req.url, req.text), 'analyze', signal),
};
