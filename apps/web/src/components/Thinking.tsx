import type { JobStatus } from '../api/types';
import { stepsOf } from '../state/steps';
import { Icon } from './Icon';

/**
 * Ход разбора как размышления (макет «A+ · Ход разбора»): что агент сейчас делает, что нашёл и что проверил.
 * Готовые шаги с галочкой и находками, текущий — с крутилкой; шаги появляются по мере работы.
 */
export function Thinking({ job }: { job: JobStatus | null }) {
  const steps = stepsOf(job);
  const eta = job?.eta_s;
  return (
    <section className="card thinking" aria-labelledby="thinking-title">
      <p className="thinking__title" id="thinking-title">
        <Icon name="model" size={18} className="thinking__spark" />
        Разбираю, что это значит для компании
      </p>
      <ol className="thinking__steps" role="status" aria-live="polite">
        {steps.map((s, i) => (
          <li key={`${i}-${s.title}`} className={`thinking__step thinking__step--${s.state} appear`}>
            <span className="thinking__dot" aria-hidden="true">
              {s.state === 'done' ? <Icon name="check" size={14} /> : s.state === 'error' ? <Icon name="warning" size={14} /> : <span className="spinner" />}
            </span>
            <span className="thinking__text">
              <span className="thinking__step-title">{s.title}</span>
              {s.detail && <span className="thinking__detail">{s.detail}</span>}
              {s.found && s.found.length > 0 && (
                <span className="thinking__found">
                  {s.found.map((f) => (
                    <span key={f} className="source-chip">
                      {f}
                    </span>
                  ))}
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
      <p className="thinking__eta">
        {eta != null && eta > 0 ? `Осталось примерно ${Math.ceil(eta)} с. ` : ''}Готовые шаги свернутся в «Как получен вывод».
      </p>
    </section>
  );
}
