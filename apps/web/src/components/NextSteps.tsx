import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useHidden } from '../state/hidden';
import { Icon } from './Icon';

type Request = 'manager' | 'application' | 'callback';

const REQUESTS: { id: Request; label: string; topic: string; done: string }[] = [
  { id: 'manager', label: 'Связаться с менеджером', topic: 'Вопрос менеджеру', done: 'Сообщение менеджеру' },
  { id: 'application', label: 'Оставить заявку', topic: 'Заявка', done: 'Заявка' },
  { id: 'callback', label: 'Заказать обратный звонок', topic: 'Обратный звонок', done: 'Обратный звонок' },
];

/**
 * Что сделать после разбора: обратиться в банк или скрыть разбор.
 * Обращение открывает форму с темой и кратким контекстом разбора — сервис ничего не оформляет сам.
 * В прототипе форма никуда не отправляется: показываем подтверждение и честно говорим об этом.
 */
export function NextSteps({
  insightId,
  eventId,
  personaId,
  title,
  context,
}: {
  insightId: string;
  /** null — разбор не из брифинга (своя новость), скрывать нечего */
  eventId: string | null;
  personaId: string;
  /** заголовок события — в тему обращения */
  title: string;
  /** краткий контекст разбора, чтобы не пересказывать менеджеру заново */
  context: string;
}) {
  const [open, setOpen] = useState<Request | null>(null);
  const [sent, setSent] = useState<Request | null>(null);
  const [topic, setTopic] = useState('');
  const [comment, setComment] = useState('');
  const { hide } = useHidden();
  const topicRef = useRef<HTMLInputElement>(null);
  const doneRef = useRef<HTMLParagraphElement>(null);
  const openers = useRef<Partial<Record<Request, HTMLButtonElement | null>>>({});
  // Куда вернуть фокус, когда форма закроется: на сообщение об отправке или на кнопку, открывшую форму.
  const focusAfter = useRef<'topic' | 'done' | Request | null>(null);
  useEffect(() => {
    const target = focusAfter.current;
    if (!target) return;
    focusAfter.current = null;
    if (target === 'topic') topicRef.current?.focus();
    else if (target === 'done') doneRef.current?.focus();
    else openers.current[target]?.focus();
  });
  const navigate = useNavigate();
  const formId = useId();
  const request = REQUESTS.find((r) => r.id === open);
  const done = REQUESTS.find((r) => r.id === sent);

  function start(r: (typeof REQUESTS)[number]) {
    setOpen(r.id);
    setSent(null);
    setTopic(`${r.topic}: ${title}`);
    setComment('');
    focusAfter.current = 'topic';
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSent(open);
    setOpen(null);
    focusAfter.current = 'done';
  }

  return (
    <section className="card next-steps" aria-labelledby="next-steps-title">
      <h2 className="card__title" id="next-steps-title">
        Обсудить с банком
      </h2>
      <div className="next-steps__buttons">
        {REQUESTS.map((r) => (
          <button
            key={r.id}
            ref={(el) => {
              openers.current[r.id] = el;
            }}
            type="button"
            className="btn btn--secondary"
            aria-expanded={open === r.id}
            aria-controls={open === r.id ? formId : undefined}
            onClick={() => start(r)}
          >
            {r.label}
          </button>
        ))}
      </div>
      {request && (
        <form id={formId} className="next-steps__form" onSubmit={onSubmit} aria-label={request.label}>
          <div className="analyze__field">
            <label htmlFor={`${formId}-topic`}>Тема</label>
            <input ref={topicRef} id={`${formId}-topic`} className="field" value={topic} onChange={(e) => setTopic(e.target.value)} />
          </div>
          <figure className="analyze__field">
            <figcaption>Контекст разбора — уйдёт вместе с обращением</figcaption>
            <p className="next-steps__context">{context}</p>
          </figure>
          <div className="analyze__field">
            <label htmlFor={`${formId}-comment`}>Комментарий</label>
            <textarea
              id={`${formId}-comment`}
              className="field analyze__text"
              rows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <div className="next-steps__buttons">
            <button type="submit" className="btn btn--primary">
              Отправить
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => {
                focusAfter.current = open;
                setOpen(null);
              }}
            >
              Отмена
            </button>
          </div>
        </form>
      )}
      <div aria-live="polite">
        {done && (
          <p className="next-steps__done" ref={doneRef} tabIndex={-1}>
            <Icon name="check" size={18} />
            {done.done}: в прототипе никуда не отправляется. В интернет-банке обращение с темой и контекстом получил бы
            ваш менеджер; оформлять ничего сервис не стал бы сам.
          </p>
        )}
      </div>
      {eventId && (
        <button
          type="button"
          className="link-button next-steps__hide"
          onClick={() => {
            hide(eventId);
            // Сигнал для качества отбора: разбор пользователю не нужен. Ошибка отправки не мешает скрыть.
            void api.feedback({ insight_id: insightId, persona_id: personaId, useful: false, reason: 'Скрыт пользователем' }).catch(() => undefined);
            navigate('/radar', { state: { hidden: eventId } });
          }}
        >
          Скрыть разбор из брифинга
        </button>
      )}
    </section>
  );
}
