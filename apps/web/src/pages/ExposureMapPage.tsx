import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { CompanyProfile, ExposureMap, FeedItem, Persona, Role, SensitivityFactor, Strength } from '../api/types';
import { factorIcon } from '../components/factorIcon';
import { Icon } from '../components/Icon';
import { ServiceTabs } from '../components/ServiceTabs';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { StatementList, type RefIndex } from '../components/Statement';
import { ChipSwitch, NowTag, Spark, StrengthMark } from '../components/WeekParts';
import { useBriefing } from '../state/briefing';
import { strengthLabel } from '../state/labels';
import { eventPath } from '../state/routes';
import { useCurrentUser, useSession } from '../state/session';
import { useAsync } from '../state/useAsync';
import { plural } from '../state/screens';
import { isHolding, riskScreen, type RiskRow, type RiskScreen } from '../state/week';

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

/** Запасной вид, пока у API нет risk-map: карта из /exposure — факторы, сила, канал и доказательства. */
function LegacyMap() {
  const { company } = useCurrentUser();
  const map = useAsync((signal) => api.exposureMap(company.id, signal), company.id);
  // События по фактору — из того же брифинга; если он не загрузился, карта всё равно работает.
  const briefing = useBriefing();
  const items = briefing.status === 'ok' ? briefing.data.items : [];

  return (
    <>
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
    </>
  );
}

// ─── Макеты B2, B3 ──────────────────────────────────────────────────────────

const ROLE_SHORT: Record<Role, string> = {
  owner: 'Собственник',
  ceo: 'Гендиректор',
  cfo: 'Финдиректор',
  chief_accountant: 'Главбух',
  treasury: 'Казначей',
  other: 'Руководитель',
};

function Legend() {
  return (
    <ul className="risk-legend">
      <li>
        <StrengthMark strength="strong" /> — прямо меняет выручку, издержки или стоимость денег
      </li>
      <li>
        <StrengthMark strength="notable" /> — через группу, лизинг, часть оборота или оценку по отрасли
      </li>
      <li>
        <StrengthMark strength="weak" /> — малая доля оборота или общий для всех фон
      </li>
    </ul>
  );
}

function RiskFactorRow({ row, index }: { row: RiskRow; index: number }) {
  return (
    <li className="risk-row appear" style={{ animationDelay: `${Math.min(index, 8) * 50}ms` }}>
      <div className="risk-row__name">
        <span className="icon-tile" aria-hidden="true">
          <Icon name={factorIcon(row.code)} />
        </span>
        <div>
          <h2 className="risk-row__title">{row.label}</h2>
          <p className="risk-row__strength">
            <StrengthMark strength={row.strength} />
            {row.estimate && (
              <span className="risk-row__estimate" title="Сила оценена по отрасли, а не посчитана по вашим данным">
                ≈ Оценка по отрасли, не по вашим данным
              </span>
            )}
          </p>
        </div>
      </div>
      <dl className="risk-row__facts">
        <dt>Почему</dt>
        <dd>{row.why || <span className="muted">Нет данных</span>}</dd>
        <dt>Сейчас</dt>
        <dd>
          {row.now ? (
            <>
              <NowTag tag={row.now.tag} />{' '}
              <Link to={eventPath(row.now.eventId)} className="risk-row__now">
                {row.now.text}
              </Link>
            </>
          ) : (
            <span className="muted">Свежих новостей по теме нет</span>
          )}
        </dd>
        <dt>Банк</dt>
        <dd>
          {row.bank ? (
            <span className="risk-row__bank">
              <Icon name="bank" size={16} />
              <span>
                <span className="risk-row__bank-text" title={row.bank.text}>
                  {row.bank.text}
                  {row.bank.outdated && <span className="risk-row__outdated"> — прогноз устарел</span>}
                </span>
                {row.bank.outdated && row.bank.note && <span className="risk-row__bank-note">{row.bank.note}</span>}
                <span className="risk-row__bank-caption">{row.bank.caption}</span>
              </span>
            </span>
          ) : (
            <span className="muted">Позиции банка по теме нет</span>
          )}
        </dd>
      </dl>
      <div className="risk-row__news">
        <p className="risk-row__news-title">Новости за неделю</p>
        {row.days.length > 0 && <Spark days={row.days} weekdays />}
        {row.newsLink ? (
          <Link to={`/radar?factor=${encodeURIComponent(row.code)}`} className="link-action">
            {row.newsLink}
            <span className="visually-hidden"> — {row.label}</span>
            <Icon name="arrowRight" size={16} />
          </Link>
        ) : (
          <span className="muted">Новостей нет</span>
        )}
      </div>
    </li>
  );
}

function RiskList({ screen }: { screen: RiskScreen }) {
  if (screen.rows.length === 0)
    return (
      <EmptyState title="Для этой компании факторы пока не рассчитаны">
        Как только у банка появятся данные о компании, здесь будет видно, к чему она уязвима.
      </EmptyState>
    );
  return (
    <ol className="card risk-list">
      {screen.rows.map((row, i) => (
        <RiskFactorRow key={row.code} row={row} index={i} />
      ))}
    </ol>
  );
}

function RiskSkeleton() {
  return (
    <ul className="card risk-list" aria-busy="true" aria-label="Загружаем факторы">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i} className="risk-row">
          <div className="risk-row__name">
            <Skeleton width={40} height={40} />
            <Skeleton width={140} height={18} />
          </div>
          <div>
            <Skeleton width="90%" />
            <Skeleton width="70%" />
            <Skeleton width="80%" />
          </div>
          <Skeleton width={110} height={40} />
        </li>
      ))}
    </ul>
  );
}

/** «К чему уязвима компания» (макеты B2, B3): факторы глазами выбранной роли, новости за неделю, позиция банка. */
export function ExposureMapPage() {
  const { persona, company } = useCurrentUser();
  // «Смотреть как» — тот же переключатель роли, что в шапке: роли этой компании, доступные учётке. Выбор меняет
  // пользователя целиком — шапка, лента и карта остаются согласованными.
  const { personas, selectPersona } = useSession();
  const colleagues: Persona[] = personas.filter((p) => p.company_id === company.id);
  const viewId = persona.id;
  const viewRole = persona.role;
  const map = useAsync((signal) => api.riskMap(company.id, viewId, viewRole, signal), `${company.id}|${viewId}`);
  const screen = map.status === 'ok' && map.data ? riskScreen(map.data, company.display_name) : null;
  const holding = isHolding(company.display_name);
  // У API ещё нет risk-map — показываем прежнюю карту, без ролей и новой легенды.
  const legacy = map.status === 'ok' && map.data === null;

  return (
    <div className="page news-page">
      <ServiceTabs />
      <section className="card risk-head appear" aria-labelledby="risk-title">
        <div className="risk-head__top">
          <h1 className="news-card__title" id="risk-title">
            {screen?.title ?? (holding ? 'К чему уязвим холдинг' : 'К чему уязвима компания')}
          </h1>
          {colleagues.length > 1 && !legacy && (
            <div className="risk-head__view">
              <span className="news-card__meta">Смотреть как</span>
              <ChipSwitch
                label="Смотреть как"
                value={viewId}
                options={colleagues.map((p) => ({ value: p.id, label: ROLE_SHORT[p.role] }))}
                onChange={selectPersona}
              />
            </div>
          )}
        </div>
        {legacy ? (
          <p className="risk-head__intro">
            Факторы, от которых зависит {holding ? 'холдинг' : 'компания'}, с силой влияния и доказательствами из данных банка.
          </p>
        ) : (
          <>
            <p className="risk-head__intro">
              {screen ? `${screen.rows.length} ${plural(screen.rows.length, ['фактор', 'фактора', 'факторов'])}, которые` : 'Факторы, которые'}{' '}
              сильнее всего задевают {holding ? 'холдинг' : 'компанию'}, — по данным банка. Порядок — для роли «
              {ROLE_SHORT[viewRole].toLowerCase()}».
            </p>
            <Legend />
          </>
        )}
      </section>

      {map.status === 'loading' && <RiskSkeleton />}
      {map.status === 'error' && <ErrorState title="Не удалось загрузить факторы" error={map.error} onRetry={map.retry} />}
      {map.status === 'ok' && (screen ? <RiskList screen={screen} /> : <LegacyMap />)}

      {screen && screen.limits.length > 0 && (
        <ul className="risk-limits">
          {screen.limits.map((l, i) => (
            <li key={i}>
              <Icon name="info" size={16} />
              {l}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
