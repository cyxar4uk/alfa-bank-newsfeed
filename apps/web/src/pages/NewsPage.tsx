import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Insight } from '../api/types';
import { Disclaimer } from '../components/Disclaimer';
import { Icon } from '../components/Icon';
import { ExpandButton, LevelBadge, LevelIcon, NewsThumb } from '../components/NewsParts';
import { ServiceTabs } from '../components/ServiceTabs';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { useBriefing } from '../state/briefing';
import { useHidden } from '../state/hidden';
import { readEvents } from '../state/read';
import { LEVEL_LABEL, newsScreen, type DayRow, type EventRow } from '../state/news';
import { eventPath } from '../state/routes';
import { plural } from '../state/screens';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Прочитано или новое: приглушённый вид с меткой либо красная точка. */
function ReadMark({ read }: { read: boolean }) {
  return read ? (
    <span className="read-mark">
      <Icon name="check" size={12} />
      Прочитано
    </span>
  ) : (
    <span className="new-dot" title="Новое">
      <span className="visually-hidden">Новое: </span>
    </span>
  );
}

function Day({ row, index, read }: { row: DayRow; index: number; read: boolean }) {
  return (
    <li className={`day-row appear${read ? ' is-read' : ''}`} style={{ animationDelay: `${index * 70}ms` }}>
      <LevelBadge level={row.level} />
      <div className="day-row__body">
        <Link to={eventPath(row.eventId)} className="day-row__headline">
          {!read && <ReadMark read={false} />}
          {row.fromModel && (
            <span className="day-row__ai" title="Вывод модели">
              <Icon name="model" size={16} />
              <span className="visually-hidden">Вывод модели: </span>
            </span>
          )}
          {row.headline}
        </Link>
        <p className="day-row__why">{row.why}</p>
        {read && <ReadMark read />}
        {row.todo && <p className="day-row__todo">Что делать: {row.todo}</p>}
      </div>
    </li>
  );
}

function Event({ row, index, read }: { row: EventRow; index: number; read: boolean }) {
  return (
    <li className={`event-row appear${read ? ' is-read' : ''}`} style={{ animationDelay: `${Math.min(index, 8) * 50}ms` }}>
      <Link to={eventPath(row.eventId)} className="event-row__thumb" tabIndex={-1} aria-hidden="true">
        <NewsThumb src={row.imageUrl} factor={row.factor} size="l" />
      </Link>
      <div className="event-row__body">
        <p className="event-row__source">
          {row.iconUrl ? <img src={row.iconUrl} alt="" className="event-row__icon" /> : <Icon name="news" size={14} />}
          {row.sourceLine}
          {read && <ReadMark read />}
        </p>
        <Link to={eventPath(row.eventId)} className="event-row__title">
          {!read && <ReadMark read={false} />}
          {row.title}
        </Link>
        <p className={`event-row__why event-row__why--${row.level}`}>
          <LevelIcon level={row.level} />
          <span>
            {LEVEL_LABEL[row.level]}: {row.why}
          </span>
        </p>
        {row.bank && (
          <p className="event-row__bank">
            <Icon name="bank" size={14} />
            {row.bank}
          </p>
        )}
      </div>
    </li>
  );
}

/** Ожидание первой сборки ленты: что происходит, с переливающимися заготовками. */
function Collecting() {
  return (
    <section className="card news-card" aria-busy="true">
      <p className="news-card__title" role="status">
        Собираю главное за день для компании
      </p>
      {[0, 1, 2].map((i) => (
        <div key={i} className="day-skeleton">
          <Skeleton width={90} height={18} />
          <div>
            <Skeleton width="70%" height={18} />
            <Skeleton width="90%" />
          </div>
        </div>
      ))}
    </section>
  );
}

/** Главная сервиса «Новости» — макет «A+ · Новости · главная». */
export function NewsPage() {
  const { persona, company } = useCurrentUser();
  const briefing = useBriefing();
  const exposure = useAsync((signal) => api.exposure(company.id, signal), company.id);
  const { hidden } = useHidden();
  // Тема живёт в адресе (?factor=): с карты «К чему уязвима компания» лента открывается уже с темой.
  const [params, setParams] = useSearchParams();
  const filter = params.get('factor');
  const setFilter = (key: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (key) next.set('factor', key);
        else next.delete('factor');
        return next;
      },
      { replace: true },
    );
  // «Показать ещё» — для текущего пользователя; при смене пользователя лента снова свёрнута.
  const [showAllFor, setShowAllFor] = useState<string | null>(null);
  const showAll = showAllFor === persona.id;
  const setShowAll = (f: (v: boolean) => boolean) => setShowAllFor(f(showAll) ? persona.id : null);

  // Разбор главного события берём только готовый (cached=true): сборку отсюда не запускаем.
  const leadId = useMemo(() => {
    if (briefing.status !== 'ok') return null;
    const top = briefing.data.items
      .filter((i) => !hidden.includes(i.event_id))
      .sort((a, b) => b.relevance.score - a.relevance.score)[0];
    return top && top.insight_ready !== false ? top.event_id : null;
  }, [briefing, hidden]);
  const lead = useAsync<Insight | null>(
    (signal) => (leadId ? api.cachedInsight(leadId, persona.id, signal).catch(() => null) : Promise.resolve(null)),
    `${leadId}|${persona.id}`,
  );

  // Прочитанное читаем при каждом заходе на ленту: карточка отмечает событие, возврат пересоздаёт страницу.
  const read = useMemo(() => readEvents(persona.id), [persona.id]);
  const screen = useMemo(
    () =>
      briefing.status === 'ok'
        ? newsScreen({
            feed: briefing.data,
            exposure: exposure.status === 'ok' ? exposure.data : null,
            hidden,
            filter,
            showAll,
            lead: lead.status === 'ok' ? lead.data : null,
            today: localToday(),
          })
        : null,
    [briefing, exposure, hidden, filter, showAll, lead],
  );

  return (
    <div className="page news-page">
      <ServiceTabs />

      {briefing.status === 'loading' && <Collecting />}
      {briefing.status === 'error' && <ErrorState title="Не удалось собрать новости" error={briefing.error} onRetry={briefing.retry} />}
      {screen?.empty && (
        <EmptyState title="Значимых событий пока нет">Как только появится событие, которое касается компании, оно будет здесь.</EmptyState>
      )}

      {screen && !screen.empty && (
        <>
          <section className="card news-card day appear" aria-labelledby="day-title">
            <div className="news-card__head">
              <h1 className="news-card__title" id="day-title">
                Главное за день
              </h1>
              <span className="news-card__meta">{screen.updated}</span>
            </div>
            {screen.day.length > 0 ? (
              <ol className="day-list">
                {screen.day.map((row, i) => (
                  <Day key={row.eventId} row={row} index={i} read={read.has(row.eventId)} />
                ))}
              </ol>
            ) : (
              <p className="day-row__why">Важного для компании сегодня нет — ниже все события дня.</p>
            )}
            {(screen.bank || screen.action) && (
              <div className="day-bank">
                {screen.bank ? (
                  <>
                    <Icon name="bank" size={18} className="day-bank__icon" />
                    <p className="day-bank__text">{screen.bank.statement}</p>
                    <span className="day-bank__caption">{screen.bank.caption}</span>
                  </>
                ) : (
                  <span className="day-bank__spacer" />
                )}
                {screen.action && (
                  <Link to={eventPath(screen.action.eventId)} state={{ openTarget: true }} className="btn btn--primary">
                    {screen.action.label}
                  </Link>
                )}
              </div>
            )}
          </section>

          <section className="events" aria-labelledby="events-title">
            <div className="events__head">
              <h2 className="events__title" id="events-title">
                События для компании
              </h2>
              <div className="chips" role="group" aria-label="Темы">
                {screen.chips.map((c) => (
                  <button
                    key={c.key ?? 'all'}
                    type="button"
                    className="chip"
                    aria-pressed={c.selected}
                    onClick={() => setFilter(c.selected ? null : c.key)}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="card news-card">
              <ul className="event-list">
                {screen.events.map((row, i) => (
                  <Event key={row.eventId} row={row} index={i} read={read.has(row.eventId)} />
                ))}
              </ul>
              {(screen.more > 0 || (showAll && !filter)) && (
                <ExpandButton
                  open={showAll}
                  onClick={() => setShowAll((v) => !v)}
                  more={`Показать ещё ${screen.more} ${plural(screen.more, ['событие', 'события', 'событий'])}`}
                  less="Свернуть"
                />
              )}
            </div>
          </section>
        </>
      )}

      <Disclaimer />
    </div>
  );
}
