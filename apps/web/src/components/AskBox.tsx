import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { api } from '../api/client';
import type { AskAnswer, Insight } from '../api/types';
import { Icon } from './Icon';
import { StatementList, type RefIndex } from './Statement';
import { topicFields, topicQuestions, type NumberField, type Topic } from '../state/topic';
import { fromInputs, numbersQuestion, readNumbers, saveNumbers, toInputs, type MyNumbers, type RateType } from '../state/mynumbers';

type Entry =
  | { id: number; question: string; status: 'loading' }
  | { id: number; question: string; status: 'ok'; answer: AskAnswer }
  | { id: number; question: string; status: 'error' };

const MAX_LENGTH = 500;

/** Подсказки-вопросы: с цифрами под тему события, потом общие и по составу разбора. */
function suggestionsFor(insight: Insight, topic: Topic): string[] {
  const list = [...topicQuestions(topic), 'Что поручить и кому?'];
  if (insight.bank_view.length > 0) list.push('Как это оценивает Альфа-Банк?');
  if (insight.exposure?.channels.some((c) => c.kind !== 'direct')) list.push('Через каких контрагентов нас это задевает?');
  return [...new Set(list)].slice(0, 4);
}

/** Черновик вопроса живёт в sessionStorage: перерисовка или возврат на карточку его не теряют. */
const draftKey = (insightId: string) => `pulse.ask.${insightId}`;
function readDraft(insightId: string): string {
  try {
    return sessionStorage.getItem(draftKey(insightId)) ?? '';
  } catch {
    return '';
  }
}
function saveDraft(insightId: string, text: string) {
  try {
    if (text) sessionStorage.setItem(draftKey(insightId), text);
    else sessionStorage.removeItem(draftKey(insightId));
  } catch {
    // без хранилища черновик живёт, пока открыта карточка
  }
}

/** Уточняющий вопрос по разбору: подсказки по контексту события, ответы с источниками. */
export function AskBox({
  insight,
  personaId,
  index,
  topic = 'other',
}: {
  insight: Insight;
  personaId: string;
  index: RefIndex;
  topic?: Topic;
}) {
  const [allFields, setAllFields] = useState(false);
  const showScenarioFields = allFields || topic === 'fx' || topic === 'rate';
  const fields = allFields ? (['debt', 'fxRevenue', 'fx', 'fuel'] as NumberField[]) : topicFields(topic);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [text, setText] = useState(() => readDraft(insight.id));
  const [nums, setNums] = useState<MyNumbers>(() => readNumbers(personaId));
  const numbersQ = numbersQuestion(nums);
  const [numsNote, setNumsNote] = useState<string | null>(null);
  const [numsBusy, setNumsBusy] = useState(false);
  // Сохранённые на сервере числа главнее черновика на устройстве.
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .inputs(personaId, ctrl.signal)
      .then((saved) => {
        if (saved) setNums(fromInputs(saved));
      })
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [personaId]);

  // Сохраняем числа в API — агент возьмёт их в расчёт; метода ещё нет — спрашиваем агента по этим числам.
  async function recalc() {
    if (!numbersQ) return;
    setNumsBusy(true);
    setNumsNote(null);
    try {
      const saved = await api.saveInputs(personaId, toInputs(nums));
      if (saved === true) setNumsNote('Сохранено. Агент возьмёт ваши числа в расчёт — строки с рублями появятся в разборе.');
      else if (saved === 'partial') {
        setNumsNote('Сохранено, кроме валютной выручки — её передаём агенту вопросом.');
        void ask(numbersQ);
      } else void ask(numbersQ);
    } catch {
      setNumsNote('Не удалось сохранить числа — попробуйте ещё раз.');
    } finally {
      setNumsBusy(false);
    }
  }
  const setNum = (patch: Partial<MyNumbers>) =>
    setNums((n) => {
      const next = { ...n, ...patch };
      saveNumbers(personaId, next);
      return next;
    });
  useEffect(() => saveDraft(insight.id, text), [insight.id, text]);
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
    if (!text.trim() || busy) return;
    void ask(text);
    setText('');
  }

  // Enter — отправить, Shift+Enter — новая строка.
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <section className="card ask" aria-labelledby="ask-title">
      <h2 className="ask__title" id="ask-title">
        Спросить о разборе
      </h2>
      <div className="ask__suggestions" role="group" aria-label="Подсказки-вопросы">
        {suggestionsFor(insight, topic).map((s) => (
          <button key={s} type="button" className="chip" disabled={busy} onClick={() => void ask(s)}>
            {s}
          </button>
        ))}
      </div>

      <details className="mynums">
        <summary>
          <Icon name="calc" size={16} />
          Мои числа — пересчитать в рублях
          <Icon name="chevronDown" size={14} className="mynums__chevron" />
        </summary>
        <form
          className="mynums__form"
          onSubmit={(e) => {
            e.preventDefault();
            void recalc();
          }}
        >
          {fields.includes('debt') && (
            <>
              <label className="mynums__field">
                <span>Мой долг, млн ₽</span>
                <input className="field" inputMode="decimal" value={nums.debt} onChange={(e) => setNum({ debt: e.target.value })} placeholder="например, 2 000" />
              </label>
              <label className="mynums__field">
                <span>Ставка по долгу</span>
                <select className="field" value={nums.rate} onChange={(e) => setNum({ rate: e.target.value as RateType })}>
                  <option value="unknown">Не знаю</option>
                  <option value="floating">Плавающая</option>
                  <option value="fixed">Фиксированная</option>
                </select>
              </label>
            </>
          )}
          {fields.includes('fxRevenue') && (
            <label className="mynums__field">
              <span>Валютная выручка в месяц, млн ₽</span>
              <input className="field" inputMode="decimal" value={nums.fxRevenue} onChange={(e) => setNum({ fxRevenue: e.target.value })} placeholder="например, 400" />
            </label>
          )}
          {fields.includes('fx') && (
            <label className="mynums__field">
              <span>Валютные закупки в месяц, млн ₽</span>
              <input className="field" inputMode="decimal" value={nums.fx} onChange={(e) => setNum({ fx: e.target.value })} placeholder="например, 150" />
            </label>
          )}
          {showScenarioFields && <>
            <label className="mynums__field"><span>Валюта расчётов (код)</span><input className="field" value={nums.fxCurrency} onChange={(e) => setNum({ fxCurrency: e.target.value })} placeholder="USD" /></label>
            <label className="mynums__field"><span>Базовый курс, ₽ за единицу валюты</span><input className="field" inputMode="decimal" value={nums.fxBaseRate} onChange={(e) => setNum({ fxBaseRate: e.target.value })} placeholder="например, 90" /></label>
            <label className="mynums__field"><span>Сценарный курс, ₽ за единицу валюты</span><input className="field" inputMode="decimal" value={nums.fxScenarioRate} onChange={(e) => setNum({ fxScenarioRate: e.target.value })} placeholder="например, 95" /></label>
            {(allFields || topic === 'rate') && <>
              <label className="mynums__field"><span>Текущая ставка по договору, % годовых</span><input className="field" inputMode="decimal" value={nums.currentRate} onChange={(e) => setNum({ currentRate: e.target.value })} placeholder="например, 16" /></label>
              <label className="mynums__field"><span>Сценарная ставка, % годовых</span><input className="field" inputMode="decimal" value={nums.scenarioRate} onChange={(e) => setNum({ scenarioRate: e.target.value })} placeholder="например, 12" /></label>
            </>}
          </>}
          {topic === 'fx' && (!nums.fxCurrency || !nums.fxBaseRate || !nums.fxScenarioRate || !nums.fxRevenue || !nums.fx) && <p className="mynums__hint" role="note">Для сопоставимого расчёта укажите поступления и закупки за один месяц, валюту и оба курса. Отсутствующую сторону можно указать как 0.</p>}
          {topic === 'rate' && nums.rate !== 'fixed' && (!nums.debt || !nums.currentRate || !nums.scenarioRate) && <p className="mynums__hint" role="note">Для расчёта изменения процентов укажите долг, тип ставки, текущую договорную и сценарную ставки.</p>}
          {fields.includes('fuel') && (
            <label className="mynums__field">
              <span>Закупка топлива в месяц, тонн</span>
              <input className="field" inputMode="decimal" value={nums.fuel} onChange={(e) => setNum({ fuel: e.target.value })} placeholder="например, 1 200" />
            </label>
          )}
          {!allFields && fields.length < 4 && (
            <button type="button" className="link-button mynums__more" onClick={() => setAllFields(true)}>
              Ещё поля: долг, валюта, топливо
            </button>
          )}
          <p className="mynums__hint">Пересчёт делает агент по формулам разбора — с допущениями и источниками. Заполните то, что знаете.</p>
          <button type="submit" className="btn btn--secondary btn--s" disabled={busy || numsBusy || !numbersQ}>
            Пересчитать для моих чисел
          </button>
          <p className="mynums__hint" role="status">
            {numsNote}
          </p>
        </form>
      </details>

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
              {e.status === 'ok' && e.answer.refusal && <p className="ask__refusal">{e.answer.refusal}</p>}
              {e.status === 'ok' && !e.answer.refusal && (
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
        <textarea
          id={inputId}
          className="field ask__field"
          rows={2}
          value={text}
          maxLength={MAX_LENGTH}
          placeholder="Например: сколько это в рублях для нас?"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="btn btn--secondary" disabled={busy || !text.trim()}>
          <Icon name="model" size={18} />
          Спросить
        </button>
      </form>
    </section>
  );
}
