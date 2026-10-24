import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Icon } from './Icon';

type Step = 'offer' | 'form' | 'done' | 'dismissed';

/**
 * Целевое действие карточки: полоса «Обсудить с менеджером …?» с одной красной кнопкой. Кнопка открывает
 * обращение с темой и контекстом разбора; в прототипе ничего никуда не отправляется — так и говорим.
 */
export function TargetAction({
  prompt,
  button,
  topic,
  context,
  openForm,
}: {
  prompt: string;
  button: string;
  topic: string;
  context: string;
  /** открыть сразу форму — из меню «Ещё» («Проверить условия …») */
  openForm: boolean;
}) {
  const [step, setStep] = useState<Step>(openForm ? 'form' : 'offer');
  const [subject, setSubject] = useState(`Обсудить ${topic}`);
  const [comment, setComment] = useState('');
  const id = useId();
  const topicRef = useRef<HTMLInputElement>(null);
  const touched = useRef(false);
  const doneRef = useRef<HTMLParagraphElement>(null);

  const [initial] = useState(step);
  useEffect(() => {
    if (step === 'form' && !(initial === 'form' && !touched.current)) topicRef.current?.focus();
    if (step === 'done') doneRef.current?.focus();
  }, [step, initial]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    touched.current = true;
    setStep('done');
  }

  if (step === 'dismissed') return null;
  if (step === 'done')
    return (
      <p className="target target--done" ref={doneRef} tabIndex={-1} role="status">
        <Icon name="check" size={18} />
        Обращение «{subject}» готово. В прототипе оно никуда не отправляется; в интернет-банке его получил бы ваш
        менеджер вместе с контекстом разбора.
      </p>
    );
  if (step === 'form')
    return (
      <form className="target target--form" onSubmit={onSubmit} aria-label="Обращение к менеджеру">
        <div className="analyze__field">
          <label htmlFor={`${id}-topic`}>Тема</label>
          <input ref={topicRef} id={`${id}-topic`} className="field" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
        <figure className="analyze__field">
          <figcaption>Контекст разбора — подставим в обращение</figcaption>
          <p className="target__context">{context}</p>
        </figure>
        <div className="analyze__field">
          <label htmlFor={`${id}-comment`}>Комментарий</label>
          <textarea
            id={`${id}-comment`}
            className="field analyze__text"
            rows={2}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
        <div className="target__buttons">
          <button type="submit" className="btn btn--primary">
            Отправить менеджеру
          </button>
          <button type="button" className="link-button" onClick={() => setStep('offer')}>
            Отмена
          </button>
        </div>
      </form>
    );
  return (
    <div className="target">
      <p className="target__prompt">{prompt}</p>
      <button
        type="button"
        className="btn btn--primary"
        onClick={() => {
          touched.current = true;
          setStep('form');
        }}
      >
        {button}
      </button>
      <button type="button" className="link-button" onClick={() => setStep('dismissed')}>
        Не сейчас
      </button>
    </div>
  );
}
