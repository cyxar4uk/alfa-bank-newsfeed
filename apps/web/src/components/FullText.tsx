import { api } from '../api/client';
import type { Source } from '../api/types';
import { highlight } from '../state/highlight';
import { useAsync } from '../state/useAsync';
import { Icon } from './Icon';
import { Skeleton } from './States';

/**
 * Новость целиком (макет «A+ · Новость целиком»): абзацы с цитатами, на которые опирается вывод, подсвечены и
 * пронумерованы. Полного текста нет — фрагмент из источника и ссылка на оригинал.
 */
export function FullText({ eventId, quotes, lead }: { eventId: string; quotes: string[]; lead: Source | undefined }) {
  const detail = useAsync((signal) => api.eventDetail(eventId, signal), eventId);
  if (detail.status === 'loading')
    return (
      <div className="fulltext" aria-busy="true">
        <Skeleton width="95%" />
        <Skeleton width="90%" />
        <Skeleton width="70%" />
      </div>
    );
  const full = detail.status === 'ok' && detail.data?.text ? detail.data.text : null;
  const text = full ?? lead?.fragment ?? null;
  const url = (detail.status === 'ok' && detail.data?.url) || lead?.url || null;
  const publisher = lead?.publisher ?? 'источника';
  let n = 0;
  return (
    <div className="fulltext">
      {text ? (
        text.split(/\n{2,}/).map((p, i) => {
          const segs = highlight(p, quotes);
          const quoted = segs.some((s) => s.mark);
          if (quoted) n += 1;
          return quoted ? (
            <p key={i} className="fulltext__quote">
              {segs.map((seg, j) => (seg.mark ? <mark key={j}>{seg.text}</mark> : seg.text))}
              <span className="fulltext__n" aria-hidden="true">
                {n}
              </span>
              <span className="visually-hidden"> (цитата {n})</span>
            </p>
          ) : (
            <p key={i}>{p}</p>
          );
        })
      ) : (
        <p className="muted">Текст этой новости недоступен.</p>
      )}
      <p className="fulltext__note">
        {n > 0 ? 'Подсвечены фрагменты, на которые опирается вывод. ' : ''}
        {full ? `Полный текст — с сайта ${publisher}.` : text ? 'Показан фрагмент новости.' : ''}
        {detail.status === 'error' && (
          <>
            {' '}
            Полный текст загрузить не удалось.{' '}
            <button type="button" className="link-button" onClick={detail.retry}>
              Повторить
            </button>
          </>
        )}
        {url && (
          <>
            {' '}
            <a href={url} target="_blank" rel="noreferrer" className="link-action">
              Открыть в источнике
              <Icon name="external" size={14} />
            </a>
          </>
        )}
      </p>
    </div>
  );
}
