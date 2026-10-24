import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { CompanyProfile, Trace, TraceStep } from '../api/types';
import { Icon } from '../components/Icon';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { FeatureView, SourceView, type RefIndex } from '../components/Statement';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

const KIND_LABEL: Record<TraceStep['kind'], string> = {
  plan: 'План',
  tool: 'Инструмент',
  llm: 'Модель',
  check: 'Самопроверка',
  retry: 'Повтор',
};

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });

function BackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  // Пришли из карточки внутри приложения — возвращаемся туда же; открыли по ссылке — в брифинг.
  return location.key !== 'default' ? (
    <button type="button" className="back-link link-button" onClick={() => navigate(-1)}>
      <Icon name="chevronLeft" size={16} />
      Назад к разбору
    </button>
  ) : (
    <Link to="/radar" className="back-link">
      <Icon name="chevronLeft" size={16} />
      Брифинг
    </Link>
  );
}

function Refs({ refs, index }: { refs: string[]; index: RefIndex }) {
  if (refs.length === 0) return null;
  return (
    <div className="refs">
      {refs.map((r) => {
        const source = index.sources[r];
        if (source) return <SourceView key={r} source={source} />;
        const feature = index.features[r];
        if (feature) return <FeatureView key={r} feature={feature} />;
        return (
          <p key={r} className="ref ref--missing">
            {r.startsWith('feat:') ? 'Признак' : 'Источник'} {r} не передан в трассе
          </p>
        );
      })}
    </div>
  );
}

function Step({ step, index }: { step: TraceStep; index: RefIndex }) {
  const status = step.kind === 'check' ? step.verdict : null;
  const usage = [
    step.model && `модель ${step.model}`,
    step.purpose,
    step.tokens_in != null && `токенов на входе ${number.format(step.tokens_in)}`,
    step.tokens_out != null && `на выходе ${number.format(step.tokens_out)}`,
    step.cost_rub != null && `${number.format(step.cost_rub)} ₽`,
  ].filter(Boolean);
  return (
    <li className={`trace-step trace-step--${step.kind} ${status ? `trace-step--${status}` : ''}`}>
      <span className="trace-step__mark" aria-hidden="true">
        {status === 'pass' ? <Icon name="check" size={16} /> : status === 'fail' ? '!' : step.n}
      </span>
      <div className="trace-step__body">
        <p className="trace-step__head">
          <span className="trace-step__kind">{KIND_LABEL[step.kind] ?? step.kind}</span>
          {step.tool && <code className="trace-step__tool">{step.tool}</code>}
          {status && (
            <span className={`status status--${status === 'pass' ? 'done' : 'warn'}`}>
              {status === 'pass' ? 'пройдена' : 'не пройдена'}
            </span>
          )}
        </p>
        {step.summary && <p className="trace-step__summary">{step.summary}</p>}
        {usage.length > 0 && <p className="trace-step__usage">{usage.join(' · ')}</p>}
        {step.input && Object.keys(step.input).length > 0 && (
          <details className="trace-step__input">
            <summary>Входные данные</summary>
            <pre>{JSON.stringify(step.input, null, 2)}</pre>
          </details>
        )}
        <Refs refs={step.output_refs ?? []} index={index} />
      </div>
    </li>
  );
}

function TraceView({ trace, company }: { trace: Trace; company: CompanyProfile }) {
  const index: RefIndex = {
    sources: Object.fromEntries((trace.sources ?? []).map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };
  // Признаки — из трассы, а если поле не передано, из ссылок шагов (инструмент профиля отдаёт feat:…).
  const featureIds =
    trace.features_used ??
    [...new Set(trace.steps.flatMap((s) => s.output_refs ?? []).filter((r) => r.startsWith('feat:')))];
  const features = featureIds.map((id) => index.features[id]).filter(Boolean);
  const llm = trace.steps.filter((s) => s.kind === 'llm');
  const models = [...new Set(llm.map((s) => s.model).filter(Boolean))];
  const cost = llm.reduce((sum, s) => sum + (s.cost_rub ?? 0), 0);
  const tokens = llm.reduce((sum, s) => sum + (s.tokens_in ?? 0) + (s.tokens_out ?? 0), 0);
  const retries = trace.steps.filter((s) => s.kind === 'retry').length;
  const checks = trace.steps.filter((s) => s.kind === 'check' && s.verdict);
  const failed = checks.filter((s) => s.verdict === 'fail').length;
  const checkText =
    checks.length === 0 ? 'не выполнялась' : failed > 0 ? `не пройдена: ${failed} из ${checks.length}` : 'пройдена';

  return (
    <>
      {trace.note && <p className="trace-note">{trace.note}</p>}
      <dl className="card trace-summary">
        <div>
          <dt>Шагов</dt>
          <dd>{trace.steps.length}</dd>
        </div>
        <div>
          <dt>Модели</dt>
          <dd>{models.length > 0 ? models.join(', ') : 'не записаны'}</dd>
        </div>
        <div>
          <dt>Токены и стоимость</dt>
          <dd>{tokens > 0 ? `${number.format(tokens)} · ${number.format(cost)} ₽` : 'не записаны'}</dd>
        </div>
        <div>
          <dt>Самопроверка</dt>
          <dd>
            {checkText}
            {retries > 0 ? `, повторов: ${retries}` : ''}
          </dd>
        </div>
      </dl>

      <section className="card" aria-labelledby="trace-features">
        <h2 className="card__title" id="trace-features">
          Признаки компании, которые повлияли на вывод
        </h2>
        {features.length > 0 ? (
          <div className="refs refs--grid">
            {features.map((f) => (
              <FeatureView key={f.id} feature={f} />
            ))}
          </div>
        ) : (
          <p className="muted">
            {featureIds.length === 0
              ? 'Трасса не передала признаков компании'
              : 'Признаки из трассы не найдены в профиле компании'}
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="trace-steps">
        <h2 className="card__title" id="trace-steps">
          Шаги агента
        </h2>
        <ol className="trace-steps">
          {trace.steps.map((s) => (
            <Step key={s.n} step={s} index={index} />
          ))}
        </ol>
      </section>
    </>
  );
}

export function TracePage() {
  const { traceId = '' } = useParams();
  const { company } = useCurrentUser();
  const trace = useAsync((signal) => api.trace(traceId, signal), traceId);

  return (
    <div className="page page--narrow">
      <header className="page-head">
        <BackButton />
        <h1 className="page-head__title">Как получен вывод</h1>
        <p className="page-head__lead">
          Шаги агента по порядку: план, инструменты и найденные источники, признаки компании, самопроверка и повторы,
          модели и расход.
        </p>
      </header>

      {trace.status === 'loading' && (
        <div className="card" aria-busy="true" aria-label="Загружаем трассу">
          <Skeleton width="40%" height={20} />
          <Skeleton width="90%" />
          <Skeleton width="80%" />
        </div>
      )}
      {trace.status === 'error' && <ErrorState title="Не удалось загрузить трассу" error={trace.error} onRetry={trace.retry} />}
      {trace.status === 'ok' && !trace.data && (
        <EmptyState title="Трассы для этого разбора нет">Агент не сохранил шаги для этого разбора.</EmptyState>
      )}
      {trace.status === 'ok' && trace.data && <TraceView trace={trace.data} company={company} />}
    </div>
  );
}
