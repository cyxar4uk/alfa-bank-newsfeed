import { useId, useState } from 'react';
import type { BankVsMarket, Estimate, Exposure, GroupImpact, ScoreTerm } from '../api/types';
import { channelLabel } from '../state/labels';
import { StatementItem, type RefIndex } from './Statement';

const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const factor = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 });
const billions = (bn: number) => `${number.format(bn)} млрд ₽`;

// ─── Через кого вас задевает (раздел A) ──────────────────────────────────────

export function ExposureChain({ exposure }: { exposure: Exposure }) {
  return (
    <div className="exposure">
      <h3 className="sub-title">Через кого вас задевает</h3>
      {exposure.channels.length > 0 ? (
        <ul className="chains">
          {exposure.channels.map((ch, i) => (
            <li key={`${ch.kind}-${ch.factor.code}-${i}`} className={`chain chain--${ch.kind}`}>
              <ol className="chain__path" aria-label="Цепочка влияния">
                <li className="chain__node chain__node--event">Событие</li>
                <li className="chain__node">{ch.factor.label}</li>
                {ch.kind !== 'direct' && <li className="chain__node">{ch.sector ?? channelLabel[ch.kind].toLowerCase()}</li>}
                <li className="chain__node chain__node--you">Вы</li>
              </ol>
              <p className="chain__text">
                <span className="chain__kind">{channelLabel[ch.kind]}.</span> {ch.text}
              </p>
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
                      <span className="chain__party-id">{c.id}</span> {c.label}
                      {c.amount_bn != null && <span className="chain__party-num">{billions(c.amount_bn)}</span>}
                      {c.share != null && <span className="chain__party-num">{percent.format(c.share)}</span>}
                      {c.intra_group && <span className="chain__intra">внутри группы</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Связь события с компанией через контрагентов не найдена</p>
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
  return (
    <div className="group-impact">
      <h3 className="sub-title">Ваша группа</h3>
      <p>
        Задеты {impact.affected.length} крупных компаний группы из {impact.companies_total} — {billions(impact.affected_revenue_bn)}{' '}
        выручки без вашей компании.
      </p>
      <table className="group-table">
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
                <span className="chain__party-id">{c.id}</span> {c.label}
              </td>
              <td className="num">{billions(c.revenue_bn)}</td>
              <td>{c.factors.map((f) => f.label).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Банк против рынка (раздел F) ────────────────────────────────────────────

export function BankVsMarketView({ data, index }: { data: BankVsMarket; index: RefIndex }) {
  return (
    <div className={`vs-market vs-market--${data.verdict}`}>
      <p className="vs-market__verdict">{data.verdict === 'diverges' ? 'Банк расходится с рынком' : 'Банк согласен'}</p>
      <p className="vs-market__summary">{data.summary}</p>
      <ul className={`stmt-list ${data.market ? 'vs-market__pair' : ''}`}>
        {data.market && <StatementItem statement={data.market} index={index} caption="Ожидание рынка" />}
        <StatementItem statement={data.bank} index={index} caption="Ожидание банка" />
      </ul>
    </div>
  );
}

// ─── Оценка в рублях (разделы C и E) ─────────────────────────────────────────

export function EstimateView({ estimate, index }: { estimate: Estimate; index: RefIndex }) {
  const [raw, setRaw] = useState('');
  const [scenarioId, setScenarioId] = useState(estimate.scenarios[0]?.id);
  const inputId = useId();
  const scenario = estimate.scenarios.find((s) => s.id === scenarioId) ?? estimate.scenarios[0];
  const amount = Number(raw.replace(/\s/g, '').replace(',', '.'));
  const valid = raw.trim() !== '' && Number.isFinite(amount) && amount >= 0;
  const result = valid && scenario ? amount * scenario.multiplier : null;

  return (
    <div className="estimate">
      <h3 className="sub-title">Оценка: {estimate.title.toLowerCase()}</h3>
      <div className="estimate__row">
        <label className="estimate__field" htmlFor={inputId}>
          <span>
            {estimate.input.label}, {estimate.input.unit}
          </span>
          <input
            id={inputId}
            type="text"
            inputMode="decimal"
            value={raw}
            placeholder="например, 1000"
            onChange={(e) => setRaw(e.target.value)}
            aria-describedby={`${inputId}-hint`}
          />
          <small id={`${inputId}-hint`}>{estimate.input.hint}</small>
        </label>
        <div className="estimate__scenarios" role="radiogroup" aria-label="Сценарий">
          {estimate.scenarios.map((s) => (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={s.id === scenario?.id}
              className="chip"
              onClick={() => setScenarioId(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="estimate__result" aria-live="polite">
        {result === null ? (
          <p className="muted">Введите сумму — без неё расчёта нет.</p>
        ) : (
          <>
            <p className="estimate__value">
              {estimate.result_label}: <strong>{number.format(result)} млн ₽</strong>
            </p>
            <p className="estimate__formula">
              {estimate.formula}: {number.format(amount)} × {factor.format(scenario.multiplier)} = {number.format(result)}
            </p>
          </>
        )}
      </div>
      {scenario && (
        <ul className="stmt-list">
          <StatementItem statement={scenario.basis} index={index} caption="Параметр сценария" />
        </ul>
      )}
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
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const max = Math.max(...terms.map((t) => t.value));
  return (
    <div className="breakdown">
      <button type="button" className="stmt__toggle" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((v) => !v)}>
        {open ? 'Скрыть разложение' : 'Почему это выше остального'}
      </button>
      {open && (
        <div id={panelId} className="breakdown__panel">
          <ul>
            {terms.map((t) => (
              <li key={t.label}>
                <span className="breakdown__label">{t.label}</span>
                <span className="breakdown__bar" aria-hidden="true">
                  <i style={{ width: `${(t.value / max) * 100}%` }} />
                </span>
                <span className="breakdown__value">{number.format(t.value)}</span>
              </li>
            ))}
          </ul>
          <p className="breakdown__total">Итого: {number.format(score)}</p>
        </div>
      )}
    </div>
  );
}
