import { useId, useRef, useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { AskAnswer, Insight } from '../api/types';
import { Icon } from './Icon';
import { StatementList, type RefIndex } from './Statement';

type Entry =
  | { id: number; question: string; status: 'loading' }
  | { id: number; question: string; status: 'ok'; answer: AskAnswer }
  | { id: number; question: string; status: 'error' };

const MAX_LENGTH = 500;

/** Подсказки-вопросы по составу разбора: спрашиваем о том, что в нём есть. */
function suggestionsFor(insight: Insight): string[] {
  const list: string[] = [];
  if (insight.bank_view.length > 0) list.push('Как это оценивает Альфа-Банк?');
  if (insight.consequences.risks.length > 0) list.push('Какие главные риски для компании?');
  if (insight.exposure?.channels.some((c) => c.kind !== 'direct')) list.push('Через каких контрагентов нас это задевает?');
  if (insight.actions.some((a) => a.kind !== 'product')) list.push('Что сделать в первую очередь?');
  list.push('На чём основан вывод?');
  return list.slice(0, 4);
}

/** Уточняющий вопрос по разбору: подсказки по контексту события, ответы с источниками. */
export function AskBox({ insight, personaId, index }: { insight: Insight; personaId: string; index: RefIndex }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [text, setText] = useState('');
  const nextId = useRef(1);
  const inputId = useId();
  const busy = entries.some((e) => e.status === 'loading');

  async function ask(question: string, replaceId?: number) {
    const q = question.trim();
    if (!q || busy) return;
    const id = replaceId ?? nextId.current++;
    setEntries((list) =>
      replaceId
        ? list.map((e) => (e.id === id ? { id, question: q, status: 'loading' } : e))
        : [...list, { id, question: q, status: 'loading' }],
    );
    try {
      const answer = await api.ask(insight.id, personaId, q);
      setEntries((list) => list.map((e) => (e.id === id ? { id, question: q, status: 'ok', answer } : e)));
    } catch {
      setEntries((list) => list.map((e) => (e.id === id ? { id, question: q, status: 'error' } : e)));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(text);
    setText('');
  }

  return (
    <section className="card ask" aria-labelledby="ask-title">
      <h2 className="card__title" id="ask-title">
        Уточнить
      </h2>
      <div className="ask__suggestions" role="group" aria-label="Подсказки-вопросы">
        {suggestionsFor(insight).map((s) => (
          <button key={s} type="button" className="chip" disabled={busy} onClick={() => void ask(s)}>
            {s}
          </button>
        ))}
      </div>

      <div aria-live="polite">
        {entries.length > 0 && (
        <ol className="ask__thread">
          {entries.map((e) => (
            <li key={e.id} className="ask__entry">
              <p className="ask__question">{e.question}</p>
              {e.status === 'loading' && <p className="muted">Ищем ответ в материалах разбора…</p>}
              {e.status === 'error' && (
                <p className="ask__error">
                  Не удалось получить ответ.{' '}
                  <button type="button" className="link-button" onClick={() => void ask(e.question, e.id)}>
                    Повторить
                  </button>
                </p>
              )}
              {e.status === 'ok' && (
                <StatementList
                  items={e.answer.answer}
                  index={{
                    sources: { ...index.sources, ...Object.fromEntries(e.answer.sources.map((s) => [s.id, s])) },
                    features: index.features,
                  }}
                />
              )}
            </li>
          ))}
        </ol>
        )}
      </div>

      <form className="ask__form" onSubmit={onSubmit}>
        <label htmlFor={inputId} className="visually-hidden">
          Ваш вопрос по разбору
        </label>
        <input
          id={inputId}
          className="field"
          type="text"
          value={text}
          maxLength={MAX_LENGTH}
          placeholder="Задайте вопрос по разбору"
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className="btn btn--secondary" disabled={busy || !text.trim()}>
          <Icon name="model" size={18} />
          Спросить
        </button>
      </form>
    </section>
  );
}
