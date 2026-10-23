import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { Insight } from '../api/types';
import { AnalysisSteps } from '../components/AnalysisSteps';
import { Icon } from '../components/Icon';
import { ServiceTabs } from '../components/ServiceTabs';
import { EmptyState, ErrorState } from '../components/States';
import { roleLabel } from '../state/labels';
import { useCurrentUser } from '../state/session';
import { InsightView } from './EventPage';

const MAX_TEXT = 20_000;

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; insight: Insight | null }
  | { status: 'error'; error: Error };

const STORE_KEY = 'pulse.analyze';

/** Последний разбор своей новости — до закрытия вкладки, чтобы вернуться к нему с экрана трассы. */
function loadSaved(personaId: string): Insight | null {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    const saved = raw ? (JSON.parse(raw) as { personaId: string; insight: Insight }) : null;
    return saved?.personaId === personaId ? saved.insight : null;
  } catch {
    return null;
  }
}

function save(personaId: string, insight: Insight | null) {
  try {
    if (insight) sessionStorage.setItem(STORE_KEY, JSON.stringify({ personaId, insight }));
    else sessionStorage.removeItem(STORE_KEY);
  } catch {
    // без хранилища разбор живёт до ухода со страницы
  }
}

function validUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Смена пользователя начинает разбор заново: результат относится к прежней компании. */
export function AnalyzePage() {
  const { persona } = useCurrentUser();
  return <AnalyzeForm key={persona.id} />;
}

function AnalyzeForm() {
  const { persona, company } = useCurrentUser();
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [state, setState] = useState<State>(() => {
    const saved = loadSaved(persona.id);
    return saved ? { status: 'ok', insight: saved } : { status: 'idle' };
  });
  const [touched, setTouched] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const urlId = useId();
  const textId = useId();

  // Уход со страницы отменяет незавершённый разбор.
  useEffect(() => () => controller.current?.abort(), []);

  // Готовый результат — фокус на его заголовок, чтобы читалка экрана сразу его объявила.
  useEffect(() => {
    if (state.status === 'ok') document.querySelector<HTMLElement>('.insight-head__title, .state--empty')?.focus();
  }, [state.status]);

  const urlError = url.trim() && !validUrl(url.trim()) ? 'Ссылка должна начинаться с http:// или https://' : null;
  const empty = !url.trim() && !text.trim();

  async function run() {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setState({ status: 'loading' });
    try {
      const insight = await api.analyze(
        { persona_id: persona.id, url: url.trim() || undefined, text: text.trim() || undefined },
        c.signal,
      );
      if (!c.signal.aborted) {
        save(persona.id, insight);
        setState({ status: 'ok', insight });
      }
    } catch (e) {
      if (!c.signal.aborted) setState({ status: 'error', error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (empty || urlError) return;
    void run();
  }

  function reset() {
    controller.current?.abort();
    save(persona.id, null);
    setState({ status: 'idle' });
  }

  if (state.status === 'ok' && state.insight) {
    return (
      <div className="page">
        <InsightView
          insight={state.insight}
          company={company}
          personaId={persona.id}
          back={
            <button type="button" className="back-link link-button" onClick={reset}>
              <Icon name="chevronLeft" size={16} />
              Разобрать другую новость
            </button>
          }
        />
      </div>
    );
  }

  return (
    <div className="page page--narrow">
      <header className="page-head">
        <ServiceTabs />
        <h1 className="page-head__title">Разобрать свою новость</h1>
        <p className="page-head__lead">
          Вставьте ссылку или текст новости — разбор будет для роли «{roleLabel[persona.role].toLowerCase()}» в компании
          «{company.display_name}».
        </p>
      </header>

      {state.status === 'loading' ? (
        <AnalysisSteps />
      ) : (
        <form className="card analyze" onSubmit={onSubmit} noValidate>
          <div className="analyze__field">
            <label htmlFor={urlId}>Ссылка на новость</label>
            <input
              id={urlId}
              className="field"
              type="url"
              inputMode="url"
              value={url}
              placeholder="https://"
              aria-invalid={Boolean(urlError)}
              aria-describedby={urlError ? `${urlId}-error` : undefined}
              onChange={(e) => setUrl(e.target.value)}
            />
            {urlError && (
              <small id={`${urlId}-error`} className="analyze__error">
                {urlError}
              </small>
            )}
          </div>
          <div className="analyze__field">
            <label htmlFor={textId}>Или текст новости</label>
            <textarea
              id={textId}
              className="field analyze__text"
              value={text}
              maxLength={MAX_TEXT}
              rows={8}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          {touched && empty && (
            <p className="analyze__error" role="alert">
              Вставьте ссылку или текст — без них разбирать нечего.
            </p>
          )}
          <button type="submit" className="btn btn--primary">
            Разобрать для компании
          </button>
        </form>
      )}

      {state.status === 'error' && <ErrorState title="Не удалось разобрать новость" error={state.error} onRetry={() => void run()} />}
      {state.status === 'ok' && !state.insight && (
        <EmptyState title="Новость не касается компании">
          Связи с «{company.display_name}» не нашлось.{' '}
          <button type="button" className="link-button" onClick={reset}>
            Разобрать другую
          </button>
        </EmptyState>
      )}
    </div>
  );
}
