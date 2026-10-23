import { useState } from 'react';
import { api } from '../api/client';
import { Icon } from './Icon';

const REASONS = ['Не про мою компанию', 'Слишком очевидно', 'Ошибка в фактах', 'Нет полезных действий'];

type Status = 'idle' | 'choosing' | 'sending' | 'sent' | 'error';

export function FeedbackBox({ insightId, personaId }: { insightId: string; personaId: string }) {
  const [status, setStatus] = useState<Status>('idle');
  const [last, setLast] = useState<{ useful: boolean; reason?: string } | null>(null);

  async function send(useful: boolean, reason?: string) {
    setLast({ useful, reason });
    setStatus('sending');
    try {
      await api.feedback({ insight_id: insightId, persona_id: personaId, useful, reason });
      setStatus('sent');
    } catch {
      setStatus('error');
    }
  }

  if (status === 'sent') {
    return (
      <div className="feedback feedback--sent" role="status">
        <Icon name="check" />
        Отзыв отправлен. По нему мы улучшаем отбор и разборы.
      </div>
    );
  }

  return (
    <div className="feedback">
      <p className="feedback__question">Разбор был полезен?</p>
      <div className="feedback__buttons">
        <button type="button" className="btn btn--secondary" disabled={status === 'sending'} onClick={() => send(true)}>
          <Icon name="thumbUp" size={18} />
          Полезно
        </button>
        <button
          type="button"
          className="btn btn--secondary"
          disabled={status === 'sending'}
          aria-expanded={status === 'choosing'}
          onClick={() => setStatus('choosing')}
        >
          <Icon name="thumbDown" size={18} />
          Не полезно
        </button>
      </div>
      {status === 'choosing' && (
        <div className="feedback__reasons">
          <p>Что не так?</p>
          {REASONS.map((r) => (
            <button key={r} type="button" className="chip" onClick={() => send(false, r)}>
              {r}
            </button>
          ))}
          <button type="button" className="chip chip--plain" onClick={() => send(false)}>
            Отправить без причины
          </button>
        </div>
      )}
      {status === 'error' && last && (
        <p className="feedback__error" role="alert">
          Отзыв не отправился.{' '}
          <button type="button" className="link-button" onClick={() => send(last.useful, last.reason)}>
            Отправить ещё раз
          </button>
        </p>
      )}
    </div>
  );
}
