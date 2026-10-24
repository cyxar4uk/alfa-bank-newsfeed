import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { BackButton } from '../components/BackButton';
import { ServiceTabs } from '../components/ServiceTabs';
import { LevelBadge, NewsThumb } from '../components/NewsParts';
import { PrototypeNote } from '../components/PrototypeNote';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { useBriefing } from '../state/briefing';
import { levelOf, matchFeed, whyOf } from '../state/news';
import { eventPath } from '../state/routes';
import { plural, shortDate } from '../state/screens';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

/** Поиск по новостям: поиск API, если он есть; иначе — по уже собранной ленте. */
export function SearchPage() {
  const [params] = useSearchParams();
  const q = (params.get('q') ?? '').trim();
  const { persona } = useCurrentUser();
  const remote = useAsync((signal) => (q ? api.search(q, persona.id, signal) : Promise.resolve(null)), `${q}|${persona.id}`);
  const briefing = useBriefing();

  const items =
    remote.status === 'ok' && remote.data
      ? remote.data.items
      : remote.status === 'ok' && briefing.status === 'ok'
        ? matchFeed(briefing.data.items, q)
        : null;

  return (
    <div className="page news-page">
      <ServiceTabs key={q} />
      <BackButton />
      <header className="news-head">
        <div className="news-head__text">
          <h1 className="news-head__title">{q ? `Поиск: «${q}»` : 'Поиск по новостям'}</h1>
          {items && <p className="news-head__sub">{`Найдено ${items.length} ${plural(items.length, ['событие', 'события', 'событий'])}`}</p>}
        </div>
      </header>
      {(remote.status === 'loading' || (remote.status === 'ok' && !remote.data && briefing.status === 'loading')) && (
        <section className="card news-card">
          <Skeleton width="70%" height={18} />
          <Skeleton width="90%" />
        </section>
      )}
      {remote.status === 'error' && <ErrorState title="Поиск не удался" error={remote.error} onRetry={remote.retry} />}
      {items && items.length === 0 && (
        <EmptyState title="Ничего не нашлось">Попробуйте другое слово: тему, издание или название показателя.</EmptyState>
      )}
      {items && items.length > 0 && (
        <section className="card news-card">
          <ul className="rest-list">
            {items.map((i, n) => (
              <li key={i.event_id} className="rest-item appear" style={{ animationDelay: `${Math.min(n, 8) * 40}ms` }}>
                <NewsThumb src={i.image_url ?? null} factor={i.factors[0]?.code ?? 'industry'} size="s" />
                <div className="rest-item__body">
                  <Link to={eventPath(i.event_id)} className="rest-item__title">
                    {i.event.title}
                  </Link>
                  <span className="rest-item__why">
                    <LevelBadge level={levelOf(i)} /> {whyOf(i)}
                  </span>
                  <span className="rest-item__meta">
                    {[shortDate(i.event.date), i.source.publisher].filter(Boolean).join(' · ')}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <PrototypeNote />
    </div>
  );
}
