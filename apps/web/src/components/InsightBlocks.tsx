import { useId, useRef, useState, type KeyboardEvent } from 'react';
import type { BankVsMarket, Estimate, Exposure, GroupImpact, ScoreTerm } from '../api/types';
import { channelLabel } from '../state/labels';
import { factorIcon } from './factorIcon';
import { Icon } from './Icon';
import { StatementItem, type RefIndex } from './Statement';

const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const factor = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 });
const billions = (bn: number) => `${number.format(bn)} млрд ₽`;

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

// ─── Через кого вас задевает (раздел A) ──────────────────────────────────────

export function ExposureChain({ exposure }: { exposure: Exposure }) {
  return (
    <div className="exposure">
      <h3 className="sub-title">Через кого вас задевает</h3>
      {exposure.channels.length > 0 ? (
        <ul className="chains">
          {exposure.channels.map((ch, i) => {
            const label = channelLabel[ch.kind] ?? 'Канал';
            return (
              <li key={`${ch.kind}-${ch.factor.code}-${i}`} className={`chain chain--${ch.kind}`}>
                <p className="chain__kind">{label}</p>
                <div className="chain__body">
                  <ol className="chain__path" aria-label={`Цепочка: ${label.toLowerCase()}`}>
                    <li className="chain__node">
                      <Icon name="fact" size={16} />
                      Событие
                    </li>
                    <li className="chain__node">
                      <Icon name={factorIcon(ch.factor.code)} size={16} />
                      {ch.factor.label}
                    </li>
                    {ch.kind !== 'direct' && ch.sector && <li className="chain__node">{ch.sector}</li>}
                    <li className="chain__node chain__node--you">Вы</li>
                  </ol>
                  <p className="chain__text">{ch.text}</p>
                  {(ch.share != null || ch.coverage != null) && (
                    <p className="chain__numbers">
                      {ch.share != null && <span>Доля в видимом банку обороте: {percent.format(ch.share)}</span>}
                      {ch.coverage != null && <span>Отрасль контрагента известна у {percent.format(ch.coverage)} оборота</span>}
                    </p>
                  )}
                  {ch.counterparties.length > 0 && (
                    <ul className="chain__parties">
                      {ch.counterparties.map((c) => (
                        <li key={c.id}>
                          <span className="chain__party-id">{c.id}</span>
                          <span>{c.label}</span>
                          {c.amount_bn != null && <span className="chain__party-num">{billions(c.amount_bn)}</span>}
                          {c.share != null && <span className="chain__party-num">{percent.format(c.share)}</span>}
                          {c.intra_group && <span className="tag">внутри группы</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="muted">Событие не связано с вашими контрагентами</p>
      )}
      {exposure.gaps.length > 0 && (
        <ul className="gaps">
          {exposure.gaps.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ─── Ваша группа (раздел I) ──────────────────────────────────────────────────

export function GroupImpactView({ impact }: { impact: GroupImpact }) {
  const n = impact.affected.length;
  if (n === 0) return null;
  return (
    <div className="group-impact">
      <h3 className="sub-title">Ваша группа</h3>
      <p>
        {plural(n, 'Задета', 'Задеты', 'Задеты')} {n} {plural(n, 'крупная компания', 'крупные компании', 'крупных компаний')}{' '}
        группы из {impact.companies_total} — {billions(impact.affected_revenue_bn)} выручки без вашей компании.
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Компания</th>
              <th scope="col" className="num">
                Выручка
              </th>
              <th scope="col">Чем задевает</th>
            </tr>
          </thead>
          <tbody>
            {impact.affected.map((c) => (
              <tr key={c.id}>
                <td>
                  <span className="table__main">{c.label}</span>
                  <span className="table__sub">{c.id}</span>
                </td>
                <td className="num">{billions(c.revenue_bn)}</td>
                <td>{c.factors.map((f) => f.label).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Банк против рынка (раздел F) ────────────────────────────────────────────

export function BankVsMarketView({ data, index }: { data: BankVsMarket; index: RefIndex }) {
  // «Расходится» — только когда есть обе стороны; иначе показываем только позицию банка.
  const diverges = data.verdict === 'diverges' && Boolean(data.market);
  const agrees = data.verdict === 'agrees';
  return (
    <div className="vs-market">
      {(diverges || agrees) && (
        <p className={`status status--${diverges ? 'warn' : 'done'}`}>
          {diverges ? 'Банк расходится с рынком' : 'Банк согласен'}
        </p>
      )}
      <p className="vs-market__summary">{data.summary}</p>
      <ul className={`stmt-list ${diverges ? 'vs-market__pair' : ''}`}>
        {diverges && data.market && <StatementItem statement={data.market} index={index} caption="Ожидание рынка" />}
        <StatementItem statement={data.bank} index={index} caption="Ожидание банка" />
      </ul>
    </div>
  );
}

// ─── Оценка в рублях (разделы C и E) ─────────────────────────────────────────

const MAX_INPUT = 1e9;

/** Сумма: цифры, пробелы между разрядами, одна запятая или точка для дробной части. */
function parseAmount(raw: string): { value: number | null; error: string | null } {
  const text = raw.replace(/\s/g, '');
  if (!text) return { value: null, error: null };
  if (!/^\d+([.,]\d+)?$/.test(text)) return { value: null, error: 'Введите число без знаков, например 1000 или 1000,5' };
  const value = Number(text.replace(',', '.'));
  if (value > MAX_INPUT) return { value: null, error: 'Слишком большое число' };
  return { value, error: null };
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = options.findIndex((o) => o.id === value);
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + options.length) % options.length;
    onChange(options[next].id);
    refs.current[next]?.focus();
  };
  return (
    <div className="segmented" role="radiogroup" aria-label={label} onKeyDown={onKey}>
      {options.map((o, i) => (
        <button
          key={o.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={o.id === value}
          tabIndex={o.id === value ? 0 : -1}
          className="segmented__item"
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function EstimateView({ estimate, index }: { estimate: Estimate; index: RefIndex }) {
  const [raw, setRaw] = useState('');
  const [scenarioId, setScenarioId] = useState(estimate.scenarios[0]?.id);
  const inputId = useId();
  const scenario = estimate.scenarios.find((s) => s.id === scenarioId) ?? estimate.scenarios[0];
  if (!scenario) return null;

  const { value, error } = parseAmount(raw);
  const result = value === null ? null : value * scenario.multiplier;

  return (
    <div className="estimate">
      <h3 className="sub-title">
        <Icon name="calc" size={18} />
        Оценка: {estimate.title.toLowerCase()}
      </h3>
      <div className="estimate__field">
        <label htmlFor={inputId}>
          {estimate.input.label}, {estimate.input.unit}
        </label>
        <input
          id={inputId}
          className="field"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={raw}
          placeholder="например, 1000"
          aria-invalid={Boolean(error)}
          aria-describedby={`${inputId}-hint`}
          onChange={(e) => setRaw(e.target.value)}
        />
        <small id={`${inputId}-hint`} className={error ? 'estimate__error' : undefined}>
          {error ?? estimate.input.hint}
        </small>
      </div>
      <Segmented
        label="Сценарий"
        options={estimate.scenarios}
        value={scenario.id}
        onChange={(id) => setScenarioId(id)}
      />
      <div className="estimate__result" aria-live="polite">
        {result === null ? (
          <p className="muted">Введите сумму — без неё не считаем.</p>
        ) : (
          <>
            <p className="estimate__value">
              {estimate.result_label}:{' '}
              <strong className="estimate__number">
                ≈ {number.format(result)} {estimate.input.unit}
              </strong>
            </p>
            <p className="estimate__formula">
              {estimate.formula}: {number.format(value ?? 0)} × {factor.format(scenario.multiplier)} = {number.format(result)}
            </p>
          </>
        )}
      </div>
      <ul className="stmt-list">
        <StatementItem statement={scenario.basis} index={index} caption="Параметр сценария" />
      </ul>
      <ul className="estimate__assumptions">
        {estimate.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </div>
  );
}

// ─── Почему это выше остального ──────────────────────────────────────────────

export function ScoreBreakdown({ terms, score }: { terms: ScoreTerm[]; score: number }) {
  const max = Math.max(0, ...terms.map((t) => t.value));
  const width = (v: number) => (max > 0 ? `${(Math.max(0, v) / max) * 100}%` : '0%');
  return (
    <div className="breakdown">
      <ul>
        {terms.map((t) => (
          <li key={t.label}>
            <span className="breakdown__label">{t.label}</span>
            <span className="breakdown__bar" aria-hidden="true">
              <i style={{ width: width(t.value) }} />
            </span>
            <span className="breakdown__value">{number.format(t.value)}</span>
          </li>
        ))}
      </ul>
      <p className="breakdown__total">Итого: {number.format(score)}</p>
    </div>
  );
}
