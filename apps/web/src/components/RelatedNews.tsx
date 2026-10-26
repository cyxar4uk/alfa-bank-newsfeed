import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { LevelIcon, NewsThumb } from './NewsParts';
import { ReadyMark } from './TrustParts';
import { levelOf, whyOf } from '../state/news';
import { eventPath } from '../state/routes';
import { shortDate } from '../state/screens';
import { readinessOf } from '../state/trust';
import { useAsync } from '../state/useAsync';

const MAX = 6;
const MIN = 1;

/** «По этой теме» под новостью: связанные события с коротким выводом для компании. Нет метода или событий — блока нет. */
export function RelatedNews({ eventId, personaId }: { eventId: string; personaId: string }) {
  const related = useAsync(
    (signal) => api.related(eventId, personaId, signal).catch(() => null),
    `${eventId}|${personaId}`,
  );
  const items = related.status === 'ok' && related.data ? related.data.filter((i) => i.event_id !== eventId).slice(0, MAX) : [];
  if (items.length < MIN) return null;
  return (
    <section className="related appear" aria-labelledby="related-title">
      <h2 className="related__title" id="related-title">
        По этой теме
      </h2>
      <ul className="related__grid">
        {items.map((i) => {
          const level = levelOf(i);
          return (
            <li key={i.event_id} className="related__card">
              <Link to={eventPath(i.event_id)} className="related__thumb" tabIndex={-1} aria-hidden="true">
                <NewsThumb src={i.image_url ?? null} factor={i.factors[0]?.code ?? 'industry'} size="l" />
              </Link>
              <p className="related__source">
                {[i.source.publisher, shortDate(i.event.date ?? i.source.published_at)].filter(Boolean).join(' · ')}
              </p>
              <Link to={eventPath(i.event_id)} className="related__headline">
                {i.event.title}
              </Link>
              <p className={`related__why event-row__why--${level}`}>
                <LevelIcon level={level} />
                <span>{whyOf(i)}</span>
              </p>
              <ReadyMark ready={readinessOf(i)} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
