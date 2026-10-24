import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { Disclaimer } from '../components/Disclaimer';
import { Icon } from '../components/Icon';
import { PrototypeNote } from '../components/PrototypeNote';
import { ServiceTabs } from '../components/ServiceTabs';
import { SourceMark } from '../components/SourceMark';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { useBriefing } from '../state/briefing';
import { useHidden } from '../state/hidden';
import { eventPath } from '../state/routes';
import { feedScreen, GROUP_HEADLINES, plural, type FeedGroup, type FeedTop } from '../state/screens';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';
import { lastVisit } from '../state/visit';

function Top({ top }: { top: FeedTop }) {
  if (top.kind === 'indicators')
    return (
      <div className="indicators">
        {top.items.map((i) => (
          <div key={i.code} className="indicator">
            <p className="indicator__label">{i.label}</p>
            <p className="indicator__value">{i.value}</p>
            {i.note && <p className="indicator__note">{i.note}</p>}
          </div>
        ))}
      </div>
    );
  return (
    <ol className="brief">
      {top.points.map((p) => (
        <li key={p.eventId}>
          <Link to={eventPath(p.eventId)} className="brief__title">
            {p.title}
          </Link>
          <span className="brief__for-you">{p.forYou}</span>
        </li>
      ))}
    </ol>
  );
}

function Group({ group }: { group: FeedGroup }) {
  const [open, setOpen] = useState(false);
  const rest = group.headlines.length - GROUP_HEADLINES;
  const headlines = open ? group.headlines : group.headlines.slice(0, GROUP_HEADLINES);
  return (
    <section className="feed-group" aria-labelledby={`g-${group.key}`}>
      <p className="feed-group__caps" id={`g-${group.key}`}>
        {group.isNew && (
          <span className="dot-new" title="Новое с прошлого визита">
            <span className="visually-hidden">новое · </span>
          </span>
        )}
        {group.caps}
      </p>
      <ul className="feed-group__news">
        {headlines.map((h, i) => (
          <li key={h.eventId} className={i === 0 ? 'headline headline--lead' : 'headline'}>
            <SourceMark mark={h.mark} />
            <span className="headline__body">
              <Link to={eventPath(h.eventId)} className="headline__title">
                {h.title}
              </Link>
              <span className="headline__source">
                {h.isNew && <span className="headline__new">новое · </span>}
                {h.sourceLine}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {rest > 0 && (
        <button type="button" className="link-button feed-group__more" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? 'Свернуть' : `Ещё ${rest} ${plural(rest, ['материал', 'материала', 'материалов'])}`}
        </button>
      )}
      <div className="for-you">
        <span className="for-you__caps">Для вас</span>
        <span className="for-you__text">{group.forYou}</span>
        {group.hasBankView && (
          <span className="for-you__bank">
            <Icon name="bank" size={14} />
            Есть позиция банка
          </span>
        )}
        <Link to={eventPath(group.openEventId)} className="link-action">
          Открыть разбор →
        </Link>
      </div>
    </section>
  );
}

/** Сводка сервиса: верх по роли и лента новостей, сгруппированная по фактору влияния (макет «Итог · 01»). */
export function FeedPage() {
  const { persona, company } = useCurrentUser();
  const briefing = useBriefing();
  const exposure = useAsync((signal) => api.exposure(company.id, signal), company.id);
  const { hidden, unhideAll } = useHidden();
  const [params, setParams] = useSearchParams();
  const [showAll, setShowAll] = useState(false);
  const filter = params.get('factor');
  const since = lastVisit(persona.id);

  const screen = useMemo(
    () =>
      briefing.status === 'ok'
        ? feedScreen({
            feed: briefing.data,
            // Карта нужна только для показателей сверху: без неё лента всё равно показывается.
            exposure: exposure.status === 'ok' ? exposure.data : null,
            role: persona.role,
            hidden,
            filter,
            lastVisit: since,
            showAll,
          })
        : null,
    [briefing, exposure, persona.role, hidden, filter, since, showAll],
  );

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

  return (
    <div className="page feed-page">
      <ServiceTabs />
      <h1 className="visually-hidden">Сводка для вас</h1>

      {briefing.status === 'loading' && (
        <div className="summary-card" aria-busy="true">
          <Skeleton width={360} height={20} />
          <Skeleton width="90%" />
          <Skeleton width="70%" />
        </div>
      )}
      {briefing.status === 'error' && (
        <ErrorState title="Не удалось загрузить ленту" error={briefing.error} onRetry={briefing.retry} />
      )}
      {screen?.empty && (
        <EmptyState title="Значимых событий пока нет">
          {screen.hiddenCount > 0 ? (
            <button type="button" className="link-button" onClick={unhideAll}>
              Вернуть скрытые события ({screen.hiddenCount})
            </button>
          ) : (
            'Как только появится событие, которое касается вашей компании, оно будет здесь.'
          )}
        </EmptyState>
      )}
      {screen && !screen.empty && (
        <>
          <section className="summary-card" aria-label="Что происходит">
            <div className="summary-card__head">
              <p className="summary-card__title">{screen.headline}</p>
              {screen.top?.kind === 'indicators' && (
                <Link to="/radar/map" className="link-action">
                  Почему эти показатели →
                </Link>
              )}
            </div>
            {screen.top && <Top top={screen.top} />}
          </section>

          <div className="chips" role="group" aria-label="Фильтр по фактору">
            {screen.chips.map((c) => (
              <button
                key={c.key ?? 'all'}
                type="button"
                className="chip"
                aria-pressed={c.selected}
                onClick={() => setFilter(c.selected ? null : c.key)}
              >
                {c.label} · {c.count}
              </button>
            ))}
          </div>

          {screen.groups.map((g) => (
            <Group key={g.key} group={g} />
          ))}

          {screen.collapsed && (
            <div className="feed-folded">
              <p>
                {screen.collapsed.expanded
                  ? `Показаны и события меньшей значимости: ${screen.collapsed.count}`
                  : `Ещё ${screen.collapsed.count} меньшей значимости: ${screen.collapsed.titles.slice(0, 5).join('; ')}${screen.collapsed.titles.length > 5 ? '…' : ''}`}
              </p>
              <button
                type="button"
                className="link-action link-button"
                aria-expanded={screen.collapsed.expanded}
                onClick={() => setShowAll((v) => !v)}
              >
                {screen.collapsed.expanded ? 'Свернуть' : 'Показать'}
              </button>
            </div>
          )}
          {screen.hiddenCount > 0 && (
            <p className="feed-hidden">
              Скрыто событий: {screen.hiddenCount}.{' '}
              <button type="button" className="link-button" onClick={unhideAll}>
                Вернуть
              </button>
            </p>
          )}
        </>
      )}

      <Disclaimer />
      <PrototypeNote />
    </div>
  );
}
