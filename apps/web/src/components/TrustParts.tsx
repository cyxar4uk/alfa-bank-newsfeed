import { useId, useState } from 'react';
import type { ClaimsView, OutdatedSignal, Readiness } from '../state/trust';
import { SUPPORT_LABEL } from '../state/trust';
import { Icon } from './Icon';

/** «Разбор готов» — откроется сразу; «Готовлю разбор» — собирается заранее, можно открыть и смотреть ход. */
export function ReadyMark({ ready }: { ready: Readiness | null }) {
  if (!ready) return null;
  return ready === 'ready' ? (
    <span className="ready-mark ready-mark--ready">
      <Icon name="check" size={12} />
      Разбор готов
    </span>
  ) : (
    <span className="ready-mark ready-mark--queued">
      <span className="ready-mark__dot" aria-hidden="true" />
      Готовлю разбор
    </span>
  );
}

const STATUS_LABEL = { verified: 'Подтверждено', partly: 'Частично', hypothesis: 'Предположение' } as const;

/** «12 из 12 утверждений подтверждены» под выводом; раскрывается: какое утверждение чем подтверждено. */
export function ClaimsCheck({ view }: { view: ClaimsView }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={`claims${view.allVerified ? ' claims--ok' : ''}`}>
      <button type="button" className="claims__toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
        <Icon name={view.allVerified ? 'check' : 'info'} size={16} />
        {view.label}
        <Icon name="chevronDown" size={14} className={open ? 'flip' : undefined} />
      </button>
      <ol className="claims__list" id={id} hidden={!open}>
        {view.rows.map((r, i) => (
          <li key={i} className={`claims__row claims__row--${r.status}`}>
            <span className="claims__status">{STATUS_LABEL[r.status]}</span>
            <span className="claims__text">{r.text}</span>
            {r.support.length > 0 && (
              <ul className="claims__support">
                {r.support.map((s, j) => (
                  <li key={j} className={`claims__src claims__src--${s.kind}`}>
                    <Icon name={s.kind === 'bank' ? 'bank' : s.kind === 'company' ? 'data' : 'fact'} size={12} />
                    <span>
                      <b>{SUPPORT_LABEL[s.kind]}</b>
                      {s.quote ? `: ${s.quote}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {r.unsupported.length > 0 && <span className="claims__unsupported">Без опоры: {r.unsupported.join(', ')}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** «Прогноз банка разошёлся с фактом» в «Главном»: по факторам карты и разбору главного события. */
export function OutdatedBanner({ signals }: { signals: OutdatedSignal[] }) {
  if (signals.length === 0) return null;
  return (
    <aside className="outdated appear" aria-label="Прогноз банка разошёлся с фактом">
      <Icon name="warning" size={18} className="outdated__icon" />
      <div>
        <p className="outdated__title">Прогноз банка разошёлся с фактом</p>
        <ul className="outdated__list">
          {signals.map((s) => (
            <li key={`${s.topic}-${s.text}`}>
              <b>{s.topic}:</b> {s.text}
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
