import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Briefing, ChannelKind, CompanyProfile, FactorRef } from '../api/types';
import { BankBadge, FeedRow, FeedSkeleton, RelevanceMeter } from '../components/FeedParts';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { StatementList, type RefIndex } from '../components/Statement';
import { channelLabel, roleLabel, SERVICE_NAME } from '../state/labels';
import { TOP_EVENTS, useBriefing } from '../state/briefing';
import { eventPath } from '../state/routes';
import { useCurrentUser } from '../state/session';

function Summary({ briefing, company }: { briefing: Briefing; company: CompanyProfile }) {
  if (briefing.summary.length === 0) return null;
  const index: RefIndex = {
    sources: Object.fromEntries((briefing.sources ?? []).map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };
  return (
    <section className="card summary" aria-labelledby="summary-title">
      <h2 className="section-title" id="summary-title">
        Что изменилось для вас
      </h2>
      <StatementList items={briefing.summary} index={index} />
    </section>
  );
}

function TopEvents({ briefing }: { briefing: Briefing }) {
  const top = briefing.items.slice(0, TOP_EVENTS);
  return (
    <section aria-labelledby="top-title">
      <h2 className="section-title" id="top-title">
        Главное
      </h2>
      <ol className="top-events">
        {top.map((item) => (
          <li key={item.event_id} className="top-event">
            <Link to={eventPath(item.event_id)} className="top-event__link">
              <span className="top-event__meta">
                <RelevanceMeter score={item.relevance.score} />
                {item.has_bank_view && <BankBadge />}
              </span>
              <span className="top-event__title">{item.event.title}</span>
              <span className="top-event__why">{item.relevance.reason}</span>
              <span className="top-event__channel">{item.channel_text}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

function uniqueFactors(briefing: Briefing): FactorRef[] {
  const seen = new Map<string, FactorRef>();
  for (const item of briefing.items) for (const f of item.factors) if (!seen.has(f.code)) seen.set(f.code, f);
  return [...seen.values()];
}

function AllEvents({ briefing }: { briefing: Briefing }) {
  const [factor, setFactor] = useState<string | null>(null);
  const [channel, setChannel] = useState<ChannelKind | null>(null);
  const factors = useMemo(() => uniqueFactors(briefing), [briefing]);
  const channels = useMemo(() => [...new Set(briefing.items.map((i) => i.channel))], [briefing]);

  const shown = briefing.items.filter(
    (i) => (!factor || i.factors.some((f) => f.code === factor)) && (!channel || i.channel === channel),
  );
  const hidden = briefing.items.length - shown.length;

  return (
    <section aria-labelledby="all-title">
      <h2 className="section-title" id="all-title">
        Все события
      </h2>
      <div className="filters">
        <div className="filters__group" role="group" aria-label="Фильтр по фактору">
          <span className="filters__label">Фактор</span>
          <button type="button" className="chip" aria-pressed={factor === null} onClick={() => setFactor(null)}>
            Все
          </button>
          {factors.map((f) => (
            <button
              key={f.code}
              type="button"
              className="chip"
              aria-pressed={factor === f.code}
              onClick={() => setFactor(factor === f.code ? null : f.code)}
            >
              {f.label}
            </button>
          ))}
        </div>
        {channels.length > 1 && (
          <div className="filters__group" role="group" aria-label="Фильтр по каналу">
            <span className="filters__label">Канал</span>
            <button type="button" className="chip" aria-pressed={channel === null} onClick={() => setChannel(null)}>
              Все
            </button>
            {channels.map((c) => (
              <button
                key={c}
                type="button"
                className="chip"
                aria-pressed={channel === c}
                onClick={() => setChannel(channel === c ? null : c)}
              >
                {channelLabel[c]}
              </button>
            ))}
          </div>
        )}
        <p className="filters__count" aria-live="polite">
          {hidden > 0 ? `Показано ${shown.length} из ${briefing.items.length}, скрыто ${hidden}` : `Событий: ${shown.length}`}
        </p>
      </div>
      {shown.length > 0 ? (
        <ul className="feed-list">
          {shown.map((item) => (
            <FeedRow key={item.event_id} item={item} />
          ))}
        </ul>
      ) : (
        <EmptyState title="Под выбранные фильтры событий нет">Сбросьте фильтр, чтобы увидеть все события.</EmptyState>
      )}
    </section>
  );
}

export function BriefingPage() {
  const { persona, company } = useCurrentUser();
  const briefing = useBriefing();

  return (
    <div className="page page--narrow">
      <header className="page-head">
        <h1 className="page-head__title">{SERVICE_NAME}</h1>
        <p className="page-head__lead">
          Брифинг для роли «{roleLabel[persona.role].toLowerCase()}» в компании «{company.display_name}». Смените
          пользователя вверху страницы — брифинг перестроится.
        </p>
      </header>

      {briefing.status === 'loading' && (
        <div className="briefing" aria-busy="true">
          <div className="card summary">
            <Skeleton width={220} height={20} />
            <Skeleton width="90%" />
            <Skeleton width="75%" />
          </div>
          <FeedSkeleton rows={3} />
        </div>
      )}
      {briefing.status === 'error' && (
        <ErrorState title="Не удалось загрузить брифинг" error={briefing.error} onRetry={briefing.retry} />
      )}
      {briefing.status === 'ok' && briefing.data.items.length === 0 && (
        <EmptyState title="Значимых событий пока нет">
          Как только появится событие, которое касается вашей компании, оно будет здесь.
        </EmptyState>
      )}
      {briefing.status === 'ok' && briefing.data.items.length > 0 && (
        <div className="briefing">
          <Summary briefing={briefing.data} company={company} />
          <TopEvents briefing={briefing.data} />
          <AllEvents briefing={briefing.data} />
        </div>
      )}
    </div>
  );
}
