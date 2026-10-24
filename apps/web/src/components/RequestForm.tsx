import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Icon } from './Icon';

export type RequestKind = 'manager' | 'application' | 'callback';

const TITLE: Record<RequestKind, string> = {
  manager: 'Сообщение менеджеру',
  application: 'Заявка',
  callback: 'Обратный звонок',
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
  const [comment, setComment] = useState('');
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
        «{subject}» готово. В прототипе никуда не отправляется; в интернет-банке его получил бы ваш менеджер вместе с
        разбором.
      </p>
    );
  return (
    <form className="request appear" onSubmit={onSubmit} aria-label={TITLE[kind]}>
      <div className="field-group">
        <label htmlFor={`${id}-s`}>Тема</label>
        <input ref={topicRef} id={`${id}-s`} className="field" value={subject} onChange={(e) => setSubject(e.target.value)} />
      </div>
      <figure className="field-group">
        <figcaption>Контекст разбора — подставим в обращение</figcaption>
        <p className="request__context">{context}</p>
      </figure>
      <div className="field-group">
        <label htmlFor={`${id}-c`}>Комментарий</label>
        <textarea id={`${id}-c`} className="field" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>
      <div className="request__buttons">
        <button type="submit" className="btn btn--primary">
          Отправить
        </button>
        <button type="button" className="btn btn--ghost" onClick={onClose}>
          Отмена
        </button>
      </div>
    </form>
  );
}
