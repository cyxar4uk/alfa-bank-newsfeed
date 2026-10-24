import type { AgentStep } from '../api/types';
import { Icon } from './Icon';

function Found({ step }: { step: AgentStep }) {
  if (!step.detail && !step.found?.length) return null;
  return (
    <>
      {step.detail && <span className="thinking__detail">{step.detail}</span>}
      {step.found && step.found.length > 0 && (
        <span className="thinking__found">
          {step.found.map((f) => (
            <span key={f} className="source-chip">
              {f}
            </span>
          ))}
        </span>
      )}
    </>
  );
}

/**
 * Ход разбора как размышления: готовые шаги сжаты в одну строку «✓ …» и раскрываются по клику, развёрнут только
 * текущий шаг — с тем, что агент сейчас делает и что нашёл.
 */
export function Thinking({ steps, eta }: { steps: AgentStep[]; eta: number | null }) {
  const current = steps.find((s) => s.state !== 'done');
  return (
    <section className="card thinking" aria-labelledby="thinking-title">
      <p className="thinking__title" id="thinking-title">
        <Icon name="model" size={18} className="thinking__spark" />
        Разбираю, что это значит для компании
      </p>
      <p className="visually-hidden" aria-live="polite">
        {current?.title ?? ''}
      </p>
      <ol className="thinking__steps">
        {steps.map((s, i) =>
          s.state === 'done' && (s.detail || s.found?.length) ? (
            <li key={`${i}-${s.title}`} className="thinking__step thinking__step--done thinking__step--fold appear">
              <details className="thinking__fold">
                <summary>
                  <span className="thinking__dot" aria-hidden="true">
                    <Icon name="check" size={14} />
                  </span>
                  <span className="thinking__step-title">{s.title}</span>
                  <Icon name="chevronDown" size={14} className="thinking__chevron" />
                </summary>
                <span className="thinking__text">
                  <Found step={s} />
                </span>
              </details>
            </li>
          ) : (
            <li key={`${i}-${s.title}`} className={`thinking__step thinking__step--${s.state} appear`}>
              <span className="thinking__dot" aria-hidden="true">
                {s.state === 'done' ? <Icon name="check" size={14} /> : s.state === 'error' ? <Icon name="warning" size={14} /> : <span className="spinner" />}
              </span>
              <span className="thinking__text">
                <span className="thinking__step-title">{s.title}</span>
                {s.state !== 'done' && <Found step={s} />}
              </span>
            </li>
          ),
        )}
      </ol>
      <p className="thinking__eta">
        {eta != null && eta > 0 ? `Осталось примерно ${Math.ceil(eta)} с. ` : ''}Когда разбор будет готов, шаги свернутся в «Как получен
        вывод».
      </p>
    </section>
  );
}
