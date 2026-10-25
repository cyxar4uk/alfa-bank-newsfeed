import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Icon } from './Icon';

export type RequestKind = 'manager' | 'application' | 'callback' | 'forward' | 'task';

const TITLE: Record<RequestKind, string> = {
  manager: 'Заявка менеджеру',
  application: 'Заявка',
  callback: 'Обратный звонок',
  forward: 'Разбор для коллеги',
  task: 'Поручение',
};

/** Кому поручить — роли, которые есть у компаний в сервисе. */
const ASSIGNEES = ['Финансовому директору', 'Казначею', 'Главному бухгалтеру', 'Генеральному директору'];
const DUE = ['Сегодня', 'На этой неделе', 'До конца квартала'];

/** Что написать после «Отправить»: кто получил бы обращение в настоящем интернет-банке. */
const DONE: Record<RequestKind, string> = {
  manager: 'в интернет-банке её получил бы ваш менеджер вместе с разбором и перезвонил.',
  application: 'в интернет-банке её получил бы ваш менеджер вместе с разбором.',
  callback: 'в интернет-банке менеджер перезвонил бы вам.',
  forward: 'в интернет-банке коллега получил бы ссылку на этот разбор.',
  task: 'в интернет-банке поручение ушло бы сотруднику с разбором и сроком.',
};

/**
 * Обращение в банк с темой и контекстом разбора. В прототипе ничего не отправляется — после «Отправить» так и
 * говорим, с анимацией смены состояния.
 */
export function RequestForm({
  kind,
  topic,
  context,
  onClose,
  focus,
}: {
  kind: RequestKind;
  topic: string;
  context: string;
  onClose: () => void;
  /** переводить ли фокус в поле темы (не нужно, когда форма открыта сразу при переходе из ленты) */
  focus: boolean;
}) {
  const [subject, setSubject] = useState(`${TITLE[kind]}: ${topic}`);
  const [comment, setComment] = useState(kind === 'task' ? topic : '');
  const [to, setTo] = useState(kind === 'task' ? ASSIGNEES[0] : '');
  const [due, setDue] = useState(DUE[1]);
  const [sent, setSent] = useState(false);
  const id = useId();
  const topicRef = useRef<HTMLInputElement>(null);
  const doneRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (focus) topicRef.current?.focus();
  }, [focus]);
  useEffect(() => {
    if (sent) doneRef.current?.focus();
  }, [sent]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSent(true);
  }

  if (sent)
    return (
      <p className="request request--done appear" ref={doneRef} tabIndex={-1} role="status">
        <span className="request__check">
          <Icon name="check" size={16} />
        </span>
        {kind === 'task'
          ? `Поручение «${comment || subject}» — ${to.toLowerCase()}, срок: ${due.toLowerCase()}.`
          : kind === 'forward'
            ? `Готово: разбор для ${to}.`
            : `Готово: «${subject}».`}{' '}
        В прототипе никуда не отправляется; {DONE[kind]}
      </p>
    );
  return (
    <form className="request appear" onSubmit={onSubmit} aria-label={TITLE[kind]}>
      {kind === 'task' ? (
        <>
          <div className="field-group">
            <label htmlFor={`${id}-to`}>Кому</label>
            <select id={`${id}-to`} className="field" value={to} onChange={(e) => setTo(e.target.value)}>
              {ASSIGNEES.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </div>
          <div className="field-group">
            <label htmlFor={`${id}-due`}>Срок</label>
            <select id={`${id}-due`} className="field" value={due} onChange={(e) => setDue(e.target.value)}>
              {DUE.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </div>
        </>
      ) : kind === 'forward' ? (
        <div className="field-group">
          <label htmlFor={`${id}-to`}>Кому</label>
          <input
            ref={topicRef}
            id={`${id}-to`}
            className="field"
            value={to}
            placeholder="Имя или почта коллеги"
            onChange={(e) => setTo(e.target.value)}
          />
        </div>
      ) : (
        <div className="field-group">
          <label htmlFor={`${id}-s`}>Тема</label>
          <input ref={topicRef} id={`${id}-s`} className="field" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
      )}
      <figure className="field-group">
        <figcaption>Контекст разбора — подставим в обращение</figcaption>
        <p className="request__context">{context}</p>
      </figure>
      <div className="field-group">
        <label htmlFor={`${id}-c`}>{kind === 'task' ? 'Что сделать' : 'Комментарий'}</label>
        <textarea id={`${id}-c`} className="field" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>
      <div className="request__buttons">
        <button type="submit" className="btn btn--primary" disabled={kind === 'forward' && !to.trim()}>
          {kind === 'task' ? 'Поручить' : kind === 'forward' ? 'Переслать' : 'Отправить'}
        </button>
        <button type="button" className="btn btn--ghost" onClick={onClose}>
          Отмена
        </button>
      </div>
    </form>
  );
}
