import { Link } from 'react-router-dom';
import type { FeedItem } from '../api/types';
import { formatDate, relevanceLevel } from '../state/labels';
import { eventPath } from '../state/routes';
import { Icon } from './Icon';
import { Skeleton } from './States';

export function BankBadge() {
  return (
    <span className="bank-badge">
      <Icon name="bank" size={14} />
      Позиция банка
    </span>
  );
}

export function RelevanceMeter({ score }: { score: number }) {
  const { label, level } = relevanceLevel(score);
  return (
    <span className={`meter meter--${level}`} title={label}>
      <span className="meter__bars" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="meter__label">{label}</span>
    </span>
  );
}

/** Событие в брифинге: значимость, «почему важно вам», канал, источник и дата. */
export function FeedRow({ item }: { item: FeedItem }) {
  return (
    <li className="feed-row">
      <Link to={eventPath(item.event_id)} className="feed-row__link">
        <div className="feed-row__top">
          <RelevanceMeter score={item.relevance.score} />
          {item.has_bank_view && <BankBadge />}
        </div>
        <h3 className="feed-row__title">{item.event.title}</h3>
        <p className="feed-row__why">
          <span className="feed-row__why-label">Почему важно вам:</span> {item.relevance.reason}
        </p>
        <p className="feed-row__meta">
          <span className="feed-row__channel">{item.channel_text}</span>
          <span>{item.source.publisher}</span>
          <time dateTime={item.event.date}>{formatDate(item.event.date)}</time>
        </p>
      </Link>
    </li>
  );
}

export function FeedSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <ul className="feed-list" aria-busy="true" aria-label="Загружаем события">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="feed-row feed-row--skeleton">
          <Skeleton width={140} height={12} />
          <Skeleton width="80%" height={20} />
          <Skeleton width="60%" />
          <Skeleton width={180} height={12} />
        </li>
      ))}
    </ul>
  );
}
