import { RELEVANCE_LEVELS } from '../state/labels';

/** Что означает каждый уровень значимости: шкала с определениями, а не только «низкая/средняя/высокая». */
export function RelevanceLegend() {
  return (
    <details className="relevance-legend">
      <summary>Что означает значимость</summary>
      <dl>
        {RELEVANCE_LEVELS.map((l) => (
          <div key={l.level}>
            <dt>
              {l.label} <span className="relevance-legend__range">{l.range}</span>
            </dt>
            <dd>{l.meaning}</dd>
          </div>
        ))}
      </dl>
      <p className="relevance-legend__note">
        Оценка от 0 до 1 учитывает силу события по фактору, уязвимость компании к нему, вес фактора для роли и
        свежесть; из чего она сложилась — в карточке события, блок «Почему это выше остального». Описания уровней —
        продуктовые; точные пороги итоговой оценки ещё уточняются.
      </p>
    </details>
  );
}
