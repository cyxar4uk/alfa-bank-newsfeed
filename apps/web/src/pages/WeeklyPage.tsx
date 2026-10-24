import { api } from '../api/client';
import type { CompanyProfile, Persona, WeeklySummary } from '../api/types';
import { factorIcon } from '../components/factorIcon';
import { Icon } from '../components/Icon';
import { ServiceTabs } from '../components/ServiceTabs';
import { PROTOTYPE_NOTICE } from '../components/Shell';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { StatementList, type RefIndex } from '../components/Statement';
import { actionKindLabel, formatDate, roleLabel } from '../state/labels';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

function Summary({ data, company, persona }: { data: WeeklySummary; company: CompanyProfile; persona: Persona }) {
  const index: RefIndex = {
    sources: Object.fromEntries((data.sources ?? []).map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };
  const footnotes = Object.fromEntries((data.sources ?? []).map((s, i) => [s.id, i + 1]));

  if (data.sections.length === 0) {
    return (
      <EmptyState title="За период значимых событий нет">
        Сводка появится, когда в брифинге будут события, которые касаются компании.
      </EmptyState>
    );
  }

  return (
    <article className="weekly">
      <header className="weekly__head">
        <p className="weekly__for">
          {company.display_name} · {roleLabel[persona.role]}
        </p>
        {data.period.from && (
          <p className="weekly__period">
            Материалы с {formatDate(data.period.from)} по {formatDate(data.period.to)}
          </p>
        )}
      </header>

      <section className="weekly__part" aria-labelledby="weekly-factors">
        <h2 className="card__title" id="weekly-factors">
          Главное по факторам
        </h2>
        {data.sections.map((s) => (
          <section key={s.factor.code} className="weekly__section">
            <h3 className="sub-title">
              <Icon name={factorIcon(s.factor.code)} size={20} />
              {s.factor.label}
            </h3>
            <StatementList items={s.statements} index={index} footnotes={footnotes} />
          </section>
        ))}
      </section>

      <section className="weekly__part block--bank" aria-labelledby="weekly-bank">
        <h2 className="card__title" id="weekly-bank">
          Позиция Альфа-Банка
        </h2>
        {data.bank_view.length > 0 ? (
          <StatementList items={data.bank_view} index={index} footnotes={footnotes} />
        ) : (
          <p className="bank-empty">Позиции банка по темам периода нет.</p>
        )}
      </section>

      <section className="weekly__part" aria-labelledby="weekly-actions">
        <h2 className="card__title" id="weekly-actions">
          Рекомендованные шаги
        </h2>
        {data.actions.length > 0 ? (
          <ul className="actions">
            {data.actions.map((a, i) => (
              <li key={`${i}-${a.text}`} className="action">
                <span className="action__kind">{actionKindLabel[a.kind]}</span>
                <span className="action__text">{a.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Конкретных шагов за период нет — откройте события в брифинге.</p>
        )}
      </section>

      {data.sources && data.sources.length > 0 && (
        <section className="weekly__part" aria-labelledby="weekly-sources">
          <h2 className="card__title" id="weekly-sources">
            Источники
          </h2>
          <ol className="weekly__sources">
            {data.sources.map((s) => {
              const page = /#p(\d+)$/.exec(s.id)?.[1];
              return (
                <li key={s.id}>
                  {s.publisher}. {s.title}
                  {page ? `, стр. ${page}` : ''}, {formatDate(s.published_at)}
                  {s.url ? ` — ${s.url}` : ''}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <footer className="weekly__footer">
        <p>{PROTOTYPE_NOTICE}</p>
        <p>Сформировано {formatDate(new Date().toISOString())}</p>
      </footer>
    </article>
  );
}

export function WeeklyPage() {
  const { persona, company } = useCurrentUser();
  const weekly = useAsync((signal) => api.weekly(persona.id, signal), persona.id);

  return (
    <div className="page page--narrow">
      <header className="page-head no-print">
        <ServiceTabs />
        <div className="page-head__row">
          <h1 className="page-head__title">Сводка недели</h1>
          {weekly.status === 'ok' && weekly.data.sections.length > 0 && (
            <button type="button" className="btn btn--secondary" onClick={() => window.print()}>
              <Icon name="documents" size={18} />
              Распечатать
            </button>
          )}
        </div>
        <p className="page-head__lead">
          Для совета директоров: главное по факторам, позиция банка и шаги. Печатается на 1–2 страницы A4.
        </p>
      </header>
      <h1 className="print-only weekly__print-title">Сводка недели</h1>

      {weekly.status === 'loading' && (
        <div className="card weekly" aria-busy="true" aria-label="Загружаем сводку">
          <Skeleton width="40%" height={20} />
          <Skeleton width="90%" />
          <Skeleton width="80%" />
          <Skeleton width="85%" />
        </div>
      )}
      {weekly.status === 'error' && (
        <ErrorState title="Не удалось загрузить сводку" error={weekly.error} onRetry={weekly.retry} />
      )}
      {weekly.status === 'ok' && <Summary data={weekly.data} company={company} persona={persona} />}
    </div>
  );
}
