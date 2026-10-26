import { useId, useState } from 'react';
import { api } from '../api/client';
import type { DataAnalysis as DataAnalysisResult } from '../api/types';
import { useAsync } from '../state/useAsync';
import './DataAnalysis.css';

const pct = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });

function indicatorText(code: string, text: string): string {
  return code.startsWith('hhi_') ? text.replace(/(\d)\.(\d)/g, '$1,$2') : text;
}

function Coverage({ name, part, hasFlows }: { name: string; part: DataAnalysisResult['quality']['industry']; hasFlows: boolean }) {
  return <div className="data-analysis__coverage"><span>{name}</span><strong>{hasFlows ? pct.format(part.coverage) : 'Нет внешних потоков'}</strong></div>;
}

function AnalysisBody({ data }: { data: DataAnalysisResult }) {
  const [showAllIndicators, setShowAllIndicators] = useState(false);
  const [showAllPaths, setShowAllPaths] = useState(false);
  const quality = data.quality;
  const indicators = data.indicators;
  const paths = data.indirect?.paths ?? [];
  const visiblePaths = showAllPaths ? paths : paths.slice(0, 3);
  return (
    <div className="data-analysis__body">
      <p className="data-analysis__note">Основа — снимок наблюдаемых платежных связей. В данных нет дат платежей, назначения и валюты. Эти показатели не описывают динамику, просрочку, прибыль или рыночную долю. Счета прототипа синтетические и не относятся к данным кейса.</p>
      <p className="data-analysis__meta">Внешних контрагентов: {quality.external_counterparties}. Исключено самоплатежей: {quality.excluded_self_payments}; выбросов: {quality.excluded_outlier_counterparties}.</p>
      <div className="data-analysis__coverage-grid" aria-label="Покрытие атрибутов платежей">
        <Coverage name="Отрасль" part={quality.industry} hasFlows={quality.industry.total_amount > 0} />
        <Coverage name="Контрагент" part={quality.counterparty} hasFlows={quality.counterparty.total_amount > 0} />
        <Coverage name="Регион" part={quality.region} hasFlows={quality.region.total_amount > 0} />
      </div>
      <h3 className="data-analysis__heading">Показатели платежей</h3>
      {indicators.length === 0 ? <p className="data-analysis__empty">Для наблюдаемых потоков нет рассчитываемых показателей.</p> : <>
        <ul className="data-analysis__indicators">
          {indicators.slice(0, showAllIndicators ? indicators.length : 5).map((item) => (
            <li key={item.code}><details><summary><span>{item.label}</span><strong>{indicatorText(item.code, item.text)}</strong></summary><p>{item.formula}</p>{item.coverage != null && <small>Покрытие: {pct.format(item.coverage)}</small>}</details></li>
          ))}
        </ul>
        {indicators.length > 5 && <button className="data-analysis__more" type="button" onClick={() => setShowAllIndicators((v) => !v)}>{showAllIndicators ? 'Свернуть показатели' : 'Показать все показатели (' + indicators.length + ')'}</button>}
      </>}
      <h3 className="data-analysis__heading">Косвенные связи второго шага</h3>
      <p className="data-analysis__note">Это гипотезы по платежным путям через посредника. Условный индекс — произведение наблюдаемых долей, а не вероятность события или возможного убытка.</p>
      {paths.length ? <>
        <ul className="data-analysis__paths">{visiblePaths.map((path, i) => (
        <li key={path.intermediary_id + ':' + path.counterparty_id + ':' + i}>
          <span>{path.direction}</span>
          <span>Посредник: {path.intermediary_name} · {path.intermediary_industry ?? 'отрасль не определена'} → конечный контрагент: {path.counterparty_name} · {path.counterparty_industry ?? 'отрасль не определена'}</span>
          <small>Доля первого плеча — {pct.format(path.first_share)}; база: {path.first_share_basis}. Доля второго плеча — {pct.format(path.second_share)}; база: {path.second_share_basis}.</small>
          <small>Покрытие отрасли второго плеча — {pct.format(path.coverage)}.</small>
          <details><summary>Условный индекс связи</summary><small>{pct.format(path.first_share)} × {pct.format(path.second_share)} = {pct.format(path.conditional_link_index)}. Это не вероятность события или возможного убытка.</small></details>
        </li>
        ))}</ul>
        {paths.length > 3 && <button className="data-analysis__more" type="button" onClick={() => setShowAllPaths((v) => !v)}>{showAllPaths ? 'Свернуть связи' : 'Ещё ' + (paths.length - 3) + ' связей'}</button>}
      </> : <p className="data-analysis__empty">Наблюдаемых путей второго шага нет.</p>}
      {data.indirect?.limitation && <p className="data-analysis__limitation">{data.indirect.limitation}</p>}
    </div>
  );
}

export function DataAnalysis({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const result = useAsync((signal) => api.dataAnalysis(companyId, undefined, signal), companyId);
  return <section className="data-analysis card">
    <button className="data-analysis__toggle" type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)}>
      <span><strong>На чём основан анализ</strong><small>Показатели, покрытие данных и гипотезы связей</small></span><span aria-hidden="true">{open ? '−' : '+'}</span>
    </button>
    {open && <div className="data-analysis__panel" id={panelId}>
      {result.status === 'loading' ? <p aria-busy="true">Загружаем платежную аналитику…</p> : result.status === 'error' ? <div role="alert"><p>Не удалось загрузить аналитику: {result.error.message}</p><button type="button" onClick={result.retry}>Повторить</button></div> : <AnalysisBody data={result.data} />}
    </div>}
  </section>;
}
