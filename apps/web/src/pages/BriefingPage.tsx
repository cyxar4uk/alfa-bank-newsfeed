import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import type { Briefing, ChannelKind, CompanyProfile, FactorRef } from '../api/types';
import { BankBadge, FeedRow, FeedSkeleton, RelevanceMeter } from '../components/FeedParts';
import { RelevanceLegend } from '../components/RelevanceLegend';
import { ServiceTabs } from '../components/ServiceTabs';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { StatementList, type RefIndex } from '../components/Statement';
import { channelLabel, roleLabel, SERVICE_NAME } from '../state/labels';
import { TOP_EVENTS, useBriefing } from '../state/briefing';
import { useHidden } from '../state/hidden';
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

function AllEvents({ briefing, all }: { briefing: Briefing; /** брифинг вместе со скрытыми — для списка факторов */ all: Briefing }) {
  // Фактор живёт в адресе: с карты чувствительности открываем брифинг уже с фильтром.
  const [params, setParams] = useSearchParams();
  const factor = params.get('factor');
  const setFactor = (code: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (code) next.set('factor', code);
        else next.delete('factor');
        return next;
      },
      { replace: true },
    );
  const [channel, setChannel] = useState<ChannelKind | null>(null);
  // Факторы — по всему брифингу: если события фактора скрыты, фильтр из адреса не должен молча пропасть.
  const factors = useMemo(() => uniqueFactors(all), [all]);
  // Фактора из адреса нет в брифинге этого пользователя (сменили пользователя, набрали руками) — сбрасываем.
  const known = factor !== null && factors.some((f) => f.code === factor);
  useEffect(() => {
    if (factor !== null && !known) setFactor(null);
    // setFactor пересоздаётся на каждом рендере
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [factor, known]);
  const sectionRef = useRef<HTMLElement>(null);
  const cameWithFactor = useRef(known);
  useEffect(() => {
    if (cameWithFactor.current) sectionRef.current?.scrollIntoView();
  }, []);
  const channels = useMemo(() => [...new Set(briefing.items.map((i) => i.channel))], [briefing]);

  const shown = briefing.items.filter(
    (i) => (!known || i.factors.some((f) => f.code === factor)) && (!channel || i.channel === channel),
  );
  const filtered = briefing.items.length - shown.length;
  const hiddenByUser = all.items.length - briefing.items.length;

  return (
    <section aria-labelledby="all-title" ref={sectionRef}>
      <h2 className="section-title" id="all-title">
        Все события
      </h2>
      <div className="filters">
        <div className="filters__group" role="group" aria-label="Фильтр по фактору">
          <span className="filters__label">Фактор</span>
          <button type="button" className="chip" aria-pressed={!known} onClick={() => setFactor(null)}>
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
          {filtered > 0 ? `Показано ${shown.length} из ${briefing.items.length} по фильтрам` : `Событий: ${shown.length}`}
        </p>
      </div>
      {shown.length > 0 ? (
        <ul className="feed-list">
          {shown.map((item) => (
            <FeedRow key={item.event_id} item={item} />
          ))}
        </ul>
      ) : (
        <EmptyState title="Под выбранные фильтры событий нет">
          {hiddenByUser > 0 && <p>Часть событий вы скрыли — их можно вернуть над сводкой.</p>}
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => {
              setFactor(null);
              setChannel(null);
            }}
          >
            Сбросить фильтры
          </button>
        </EmptyState>
      )}
    </section>
  );
}

/** Скрытые пользователем события: что скрыто и как вернуть. */
function HiddenEvents({ briefing }: { briefing: Briefing }) {
  const { hidden, unhide, unhideAll } = useHidden();
  const items = briefing.items.filter((i) => hidden.includes(i.event_id));
  if (items.length === 0) return null;
  return (
    <details className="hidden-events">
      <summary>Скрыто событий: {items.length}</summary>
      <ul>
        {items.map((i) => (
          <li key={i.event_id}>
            <span>{i.event.title}</span>
            <button type="button" className="link-button" onClick={() => unhide(i.event_id)}>
              Вернуть
            </button>
          </li>
        ))}
      </ul>
      {items.length > 1 && (
        <button type="button" className="link-button" onClick={unhideAll}>
          Вернуть все
        </button>
      )}
    </details>
  );
}

export function BriefingPage() {
  const { persona, company } = useCurrentUser();
  const briefing = useBriefing();
  const { hidden } = useHidden();
  const location = useLocation();
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  // Пришли из карточки после «Скрыть»: объявляем и переводим фокус на заголовок. Состояние перехода сразу чистим,
  // чтобы сообщение не всплывало снова после перезагрузки или «Назад».
  const [justHidden] = useState(() => (location.state as { hidden?: string } | null)?.hidden ?? null);
  useEffect(() => {
    if (!justHidden) return;
    titleRef.current?.focus();
    navigate('.', { replace: true, state: null, preventScrollReset: true });
    // только при входе на страницу
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const hiddenTitle =
    justHidden && briefing.status === 'ok' ? briefing.data.items.find((i) => i.event_id === justHidden)?.event.title : null;
  // Скрытые пользователем события не показываем ни в «Главном», ни в списке.
  const visible = useMemo(
    () =>
      briefing.status === 'ok'
        ? { ...briefing.data, items: briefing.data.items.filter((i) => !hidden.includes(i.event_id)) }
        : null,
    [briefing, hidden],
  );

  return (
    <div className="page page--narrow">
      <header className="page-head">
        <ServiceTabs />
        <h1 className="page-head__title" ref={titleRef} tabIndex={-1}>
          {SERVICE_NAME}
        </h1>
        <p className="page-head__lead">
          Брифинг для роли «{roleLabel[persona.role].toLowerCase()}» в компании «{company.display_name}». Смените
          пользователя вверху страницы — брифинг перестроится.
        </p>
        <RelevanceLegend />
      </header>

      <p className="hidden-events__notice" aria-live="polite">
        {hiddenTitle ? `Разбор «${hiddenTitle}» скрыт из брифинга. Вернуть можно в списке скрытых.` : ''}
      </p>

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
      {briefing.status === 'ok' && <HiddenEvents briefing={briefing.data} />}
      {visible && visible.items.length === 0 && (
        <EmptyState title="Значимых событий пока нет">
          {briefing.status === 'ok' && briefing.data.items.length > 0
            ? 'Все события брифинга вы скрыли. Вернуть их можно выше.'
            : 'Как только появится событие, которое касается вашей компании, оно будет здесь.'}
        </EmptyState>
      )}
      {visible && visible.items.length > 0 && (
        <div className="briefing">
          <Summary briefing={visible} company={company} />
          <TopEvents briefing={visible} />
          <AllEvents briefing={visible} all={briefing.status === 'ok' ? briefing.data : visible} />
        </div>
      )}
    </div>
  );
}
