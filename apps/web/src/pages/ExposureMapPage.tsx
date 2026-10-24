import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { CompanyProfile, ExposureMap, FeedItem, SensitivityFactor, Strength } from '../api/types';
import { factorIcon } from '../components/factorIcon';
import { Icon } from '../components/Icon';
import { ServiceTabs } from '../components/ServiceTabs';
import { BackButton } from '../components/BackButton';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { StatementList, type RefIndex } from '../components/Statement';
import { useBriefing } from '../state/briefing';
import { strengthLabel } from '../state/labels';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

const ORDER: Record<Strength, number> = { high: 0, medium: 1, low: 2, none: 3, no_data: 4 };
const FILLED: Record<Strength, number> = { high: 3, medium: 2, low: 1, none: 0, no_data: 0 };
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 0 });

function StrengthScale({ strength }: { strength: Strength }) {
  return (
    <span className={`strength strength--${strength}`}>
      <span className="visually-hidden">Сила влияния: </span>
      <span className="strength__bar" aria-hidden="true">
        {[1, 2, 3].map((n) => (
          <i key={n} className={n <= FILLED[strength] ? 'is-on' : undefined} />
        ))}
      </span>
      <span className="strength__label">{strengthLabel[strength]}</span>
    </span>
  );
}

function FactorRow({ item, index, events }: { item: SensitivityFactor; index: RefIndex; events: FeedItem[] }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <li className="map-row">
      <span className="icon-tile" aria-hidden="true">
        <Icon name={factorIcon(item.factor.code)} />
      </span>
      <div className="map-row__main">
        <div className="map-row__head">
          <h2 className="map-row__title">{item.factor.label}</h2>
          <StrengthScale strength={item.strength} />
        </div>
        <p className="map-row__channel">{item.channel_text}</p>
        {item.coverage != null && (
          <p className="map-row__coverage">Отрасль контрагентов известна у {percent.format(item.coverage)} оборота</p>
        )}
        <div className="map-row__actions">
          {item.evidence.length > 0 && (
            <button
              type="button"
              className="stmt__toggle"
              aria-expanded={open}
              aria-controls={panelId}
              onClick={() => setOpen((v) => !v)}
            >
              {open ? 'Скрыть доказательства' : 'На чём основано'}
              <span className="visually-hidden"> — {item.factor.label}</span>
              <Icon name="chevronDown" size={14} className={open ? 'flip' : undefined} />
            </button>
          )}
          {events.length > 0 && (
            <Link to={`/radar?factor=${encodeURIComponent(item.factor.code)}`} className="link-action">
              Событий в брифинге: {events.length}
              <span className="visually-hidden"> — {item.factor.label}</span>
            </Link>
          )}
        </div>
        <div id={panelId} className="map-row__evidence" hidden={!open}>
          {open && <StatementList items={item.evidence} index={index} />}
        </div>
      </div>
    </li>
  );
}

function MapView({ map, company, items }: { map: ExposureMap; company: CompanyProfile; items: FeedItem[] }) {
  const index: RefIndex = {
    sources: Object.fromEntries((map.sources ?? []).map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };
  const factors = [...map.factors].sort((a, b) => ORDER[a.strength] - ORDER[b.strength]);
  const gaps = factors.filter((f) => f.strength === 'no_data' || (f.coverage != null && f.coverage < 0.5));
  const position = map.position ?? company.industry ?? null;
  const warnings = map.warnings ?? [];

  if (factors.length === 0) {
    return (
      <EmptyState title="Карта для этой компании пока не рассчитана">
        Факторы и их силу считает API; для этой компании расчёта ещё нет.
      </EmptyState>
    );
  }

  return (
    <>
      {position && (
        <p className="map-position">
          Положение в отрасли: № {position.rank} по выручке из {position.total} компаний с ОКВЭД {position.okved} —
          среди компаний в данных банка
        </p>
      )}
      {(gaps.length > 0 || warnings.length > 0) && (
        <aside className="warnings" aria-label="Неполные данные">
          <Icon name="warning" />
          <div>
            <p className="warnings__title">Карта неполная</p>
            <ul>
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
              {gaps.map((g) => (
                <li key={g.factor.code}>
                  {g.factor.label}:{' '}
                  {g.strength === 'no_data'
                    ? 'нет данных'
                    : `отрасль контрагентов известна лишь у ${percent.format(g.coverage ?? 0)} оборота`}
                </li>
              ))}
            </ul>
          </div>
        </aside>
      )}
      <ul className="card map-list">
        {factors.map((f) => (
          <FactorRow
            key={f.factor.code}
            item={f}
            index={index}
            events={items.filter((i) => i.factors.some((x) => x.code === f.factor.code))}
          />
        ))}
      </ul>
    </>
  );
}

export function ExposureMapPage() {
  const { company } = useCurrentUser();
  const map = useAsync((signal) => api.exposureMap(company.id, signal), company.id);
  // События по фактору — из того же брифинга; если он не загрузился, карта всё равно работает.
  const briefing = useBriefing();
  const items = briefing.status === 'ok' ? briefing.data.items : [];

  return (
    <div className="page page--narrow">
      <header className="page-head">
        <ServiceTabs />
        <BackButton />
        <h1 className="page-head__title">К чему уязвима компания</h1>
        <p className="page-head__lead">
          Факторы, от которых зависит «{company.display_name}», с силой влияния, каналом и доказательствами из данных
          банка. Смена компании перестраивает карту целиком.
        </p>
      </header>

      {map.status === 'loading' && (
        <ul className="card map-list" aria-busy="true" aria-label="Загружаем карту">
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="map-row">
              <Skeleton width={40} height={40} />
              <span className="map-row__main">
                <Skeleton width="50%" height={18} />
                <Skeleton width="70%" />
              </span>
            </li>
          ))}
        </ul>
      )}
      {map.status === 'error' && <ErrorState title="Не удалось загрузить карту" error={map.error} onRetry={map.retry} />}
      {map.status === 'ok' && <MapView map={map.data} company={company} items={items} />}
    </div>
  );
}
