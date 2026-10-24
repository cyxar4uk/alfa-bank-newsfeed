import type { EventDetail, Source } from '../api/types';
import { highlight } from '../state/highlight';
import type { AsyncState } from '../state/useAsync';
import { Icon } from './Icon';
import { Skeleton } from './States';

/**
 * Новость целиком (макет «A+ · Новость целиком»): показывается сразу, параллельно с разбором. Полного текста нет —
 * первый абзац из источника и ссылка на оригинал. Когда разбор готов, абзацы с цитатами, на которые опирается
 * вывод, подсвечены и пронумерованы.
 */
export function FullText({
  detail,
  quotes,
  lead,
}: {
  detail: AsyncState<EventDetail | null> & { retry: () => void };
  quotes: string[];
  /** источник из разбора — запасной фрагмент, если новости по адресу события нет */
  lead?: Source;
}) {
  if (detail.status === 'loading')
    return (
      <div className="fulltext" aria-busy="true">
        <Skeleton width="95%" />
        <Skeleton width="90%" />
        <Skeleton width="70%" />
      </div>
    );
  const d = detail.status === 'ok' ? detail.data : null;
  const full = d?.text || null;
  const text = full ?? d?.source?.fragment ?? lead?.fragment ?? null;
  const url = d?.source?.url || d?.url || lead?.url || null;
  const publisher = d?.source?.publisher ?? lead?.publisher ?? 'источника';
  let n = 0;
  return (
    <div className="fulltext">
      {text ? (
        text.split(/\n{2,}/).map((p, i) => {
          const segs = highlight(p, quotes);
          const quoted = segs.some((s) => s.mark);
          // Короткий абзац с цитатой — выделяем блоком; в длинном — только саму цитату с номером.
          if (quoted && p.length > 400)
            return (
              <p key={i}>
                {segs.map((seg, j) => {
                  if (!seg.mark) return seg.text;
                  n += 1;
                  return (
                    <span key={j}>
                      <mark className="fulltext__mark">{seg.text}</mark>
                      <sup className="fulltext__sup" aria-hidden="true">
                        {n}
                      </sup>
                      <span className="visually-hidden"> (цитата {n})</span>
                    </span>
                  );
                })}
              </p>
            );
          if (quoted) n += 1;
          return quoted ? (
            <p key={i} className="fulltext__quote appear">
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
        {full ? `Полный текст — с сайта ${publisher}.` : text ? 'Показано начало новости.' : ''}
        {detail.status === 'error' && (
          <>
            {' '}
            Новость загрузить не удалось.{' '}
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
