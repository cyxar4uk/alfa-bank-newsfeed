import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { CompanyProfile, Insight, Statement } from '../api/types';
import { AnalysisSteps } from '../components/AnalysisSteps';
import { RelevanceMeter } from '../components/FeedParts';
import { FeedbackBox } from '../components/FeedbackBox';
import { Icon } from '../components/Icon';
import { BankVsMarketView, EstimateView, ExposureChain, GroupImpactView, ScoreBreakdown } from '../components/InsightBlocks';
import { EmptyState, ErrorState } from '../components/States';
import { FeatureView, OriginTag, SourceView, StatementList, type RefIndex } from '../components/Statement';
import {
  actionKindLabel,
  featureValue,
  formatDate,
  legendOrigins,
  missingLabel,
  originHint,
  roleLabel,
} from '../state/labels';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

const checkLabel: Record<string, string> = {
  refs: 'У каждого факта и позиции банка есть источник',
  facts_in_source: 'Факты сверены с текстом источников',
  no_contradiction: 'Выводы не противоречат друг другу',
  multi_factor: 'Учтено несколько факторов, а не одна новость',
};

function Block({ n, title, children, tone }: { n: number; title: string; children: ReactNode; tone?: 'bank' }) {
  return (
    <section className={`block ${tone ? `block--${tone}` : ''}`} aria-labelledby={`block-${n}`}>
      <h2 className="block__title" id={`block-${n}`}>
        <span className="block__n">{n}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Statements({ items, index, empty }: { items: Statement[]; index: RefIndex; empty: string }) {
  return items.length > 0 ? <StatementList items={items} index={index} /> : <p className="muted">{empty}</p>;
}

function BackLink() {
  return (
    <Link to="/radar" className="back-link">
      <Icon name="chevronLeft" size={16} />
      Все события
    </Link>
  );
}

/** Дата самого свежего материала банка, на который опирается позиция. */
function bankMaterialDate(insight: Insight, index: RefIndex): string | null {
  const dates = insight.bank_view
    .flatMap((s) => s.refs)
    .map((r) => index.sources[r]?.published_at)
    .filter((d): d is string => Boolean(d))
    .sort();
  return dates.length > 0 ? dates[dates.length - 1] : null;
}

function InsightView({ insight, company, personaId }: { insight: Insight; company: CompanyProfile; personaId: string }) {
  const index: RefIndex = {
    sources: Object.fromEntries(insight.sources.map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };
  const { risks, opportunities, factors } = insight.consequences;
  const usedFeatures = insight.features_used.map((id) => index.features[id]).filter(Boolean);
  const missing = company.missing.map((code) => missingLabel[code] ?? code);
  const news = insight.sources.filter((s) => s.kind === 'news');
  const analytics = insight.sources.filter((s) => s.kind === 'alfa_analytics');
  const steps = insight.actions.filter((a) => a.kind !== 'product');
  // Предложение продукта — отдельно от анализа и не больше одного на карточку.
  const offer = insight.actions.find((a) => a.kind === 'product');
  const bankDate = bankMaterialDate(insight, index);

  return (
    <div className="insight">
      <div className="insight__main">
        <header className="insight-head">
          <BackLink />
          <p className="insight-head__date">{formatDate(insight.event.date)}</p>
          <h1 className="insight-head__title">{insight.event.title}</h1>
          <div className="insight-head__relevance">
            <RelevanceMeter score={insight.relevance.score} />
            <span>{insight.relevance.reason}</span>
          </div>
        </header>

        {insight.quality.warnings.length > 0 && (
          <aside className="warnings" aria-label="Ограничения разбора">
            <Icon name="warning" />
            <div>
              <p className="warnings__title">Чего не хватило для точного вывода</p>
              <ul>
                {insight.quality.warnings.map((w, i) => (
                  <li key={`${i}-${w}`}>{w}</li>
                ))}
              </ul>
            </div>
          </aside>
        )}

        <Block n={1} title="Что произошло">
          <Statements items={insight.what_happened} index={index} empty="Фактов из источников нет" />
        </Block>

        <Block n={2} title="Почему это важно вам">
          <Statements items={insight.why_it_matters} index={index} empty="Связь с компанией не описана" />
          {insight.exposure && <ExposureChain exposure={insight.exposure} />}
          {insight.group_impact && <GroupImpactView impact={insight.group_impact} />}
        </Block>

        <Block n={3} title="Риски и возможности">
          <div className="two-col">
            <div>
              <h3 className="sub-title sub-title--risk">Риски</h3>
              <Statements items={risks} index={index} empty="Модель не выделила рисков" />
            </div>
            <div>
              <h3 className="sub-title sub-title--opportunity">Возможности</h3>
              <Statements items={opportunities} index={index} empty="Модель не выделила возможностей" />
            </div>
          </div>
          {factors.length > 0 && (
            <>
              <h3 className="sub-title">От чего зависит развитие ситуации</h3>
              <StatementList items={factors} index={index} />
            </>
          )}
          {insight.estimates?.map((e) => (
            <EstimateView key={e.id} estimate={e} index={index} />
          ))}
        </Block>

        <Block n={4} title="Позиция Альфа-Банка" tone="bank">
          {insight.bank_view.length > 0 ? (
            <>
              {bankDate && <p className="bank-date">По материалам аналитиков банка от {formatDate(bankDate)}</p>}
              <StatementList items={insight.bank_view} index={index} />
              {insight.bank_vs_market && <BankVsMarketView data={insight.bank_vs_market} index={index} />}
            </>
          ) : (
            <p className="bank-empty">
              Позиции банка по теме нет. Всё, что отмечено как «вывод модели», — интерпретация модели без опоры на
              позицию банка.
            </p>
          )}
        </Block>

        <Block n={5} title="Что можно сделать">
          {steps.length > 0 ? (
            <ul className="actions">
              {steps.map((a, i) => (
                <li key={`${i}-${a.text}`} className="action">
                  <span className="action__kind">{actionKindLabel[a.kind]}</span>
                  <span className="action__text">{a.text}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Конкретных шагов модель не предложила</p>
          )}
        </Block>

        {offer && (
          <aside className="offer" aria-label="Предложение банка">
            <span className="offer__icon" aria-hidden="true">
              <Icon name="offer" size={24} />
            </span>
            <div>
              <OriginTag origin="offer" />
              <p className="offer__text">{offer.text}</p>
              <p className="offer__note">Продукт банка. Это предложение, а не вывод анализа.</p>
            </div>
          </aside>
        )}

        <Block n={6} title="На чём основано">
          {news.length > 0 && (
            <>
              <h3 className="sub-title">Новости</h3>
              <div className="refs refs--grid">
                {news.map((s) => (
                  <SourceView key={s.id} source={s} />
                ))}
              </div>
            </>
          )}
          {analytics.length > 0 && (
            <>
              <h3 className="sub-title">Аналитика Альфа-Банка</h3>
              <div className="refs refs--grid">
                {analytics.map((s) => (
                  <SourceView key={s.id} source={s} />
                ))}
              </div>
            </>
          )}
          {usedFeatures.length > 0 && (
            <>
              <h3 className="sub-title">Признаки вашей компании</h3>
              <div className="refs refs--grid">
                {usedFeatures.map((f) => (
                  <FeatureView key={f.id} feature={f} />
                ))}
              </div>
            </>
          )}
          {news.length + analytics.length + usedFeatures.length === 0 && <p className="muted">Источников в ответе нет</p>}
          {insight.quality.checks_passed.length > 0 && (
            <>
              <h3 className="sub-title">Проверки перед показом</h3>
              <ul className="checks">
                {insight.quality.checks_passed.map((c) => (
                  <li key={c}>
                    <Icon name="check" size={16} />
                    {checkLabel[c] ?? c}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Block>

        <FeedbackBox insightId={insight.id} personaId={personaId} />
      </div>

      <aside className="insight__rail">
        <section className="rail-card">
          <h2 className="rail-card__title">Как читать разбор</h2>
          <ul className="legend">
            {legendOrigins.map((o) => (
              <li key={o}>
                <OriginTag origin={o} />
                <span>{originHint[o]}</span>
              </li>
            ))}
          </ul>
        </section>
        {insight.relevance.breakdown && insight.relevance.breakdown.length > 0 && (
          <section className="rail-card">
            <h2 className="rail-card__title">Почему это выше остального</h2>
            <ScoreBreakdown terms={insight.relevance.breakdown} score={insight.relevance.score} />
          </section>
        )}
        <section className="rail-card">
          <h2 className="rail-card__title">Что учтено о компании</h2>
          {usedFeatures.length > 0 ? (
            <dl className="rail-features">
              {usedFeatures.map((f) => (
                <div key={f.id}>
                  <dt>{f.label}</dt>
                  <dd>{featureValue(f.value)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="muted">Признаки компании в выводе не использованы</p>
          )}
          {missing.length > 0 && <p className="rail-missing">Нет в данных: {missing.join(', ')}</p>}
        </section>
      </aside>
    </div>
  );
}

export function EventPage() {
  const { eventId = '' } = useParams();
  const { persona, company } = useCurrentUser();
  const insight = useAsync((signal) => api.insight(eventId, persona.id, signal), `${eventId}|${persona.id}`);

  if (insight.status === 'loading') {
    return (
      <div className="page page--narrow">
        <BackLink />
        <AnalysisSteps />
      </div>
    );
  }
  if (insight.status === 'error') {
    return (
      <div className="page page--narrow">
        <BackLink />
        <ErrorState title="Не удалось подготовить разбор" error={insight.error} onRetry={insight.retry} />
      </div>
    );
  }
  if (!insight.data) {
    return (
      <div className="page page--narrow">
        <BackLink />
        <EmptyState title="Это событие не касается выбранной компании">
          Для роли «{roleLabel[persona.role].toLowerCase()}» в компании «{company.display_name}» связи с событием не
          нашлось. Вернитесь к брифингу — там события, отобранные для вас.
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="page">
      <InsightView insight={insight.data} company={company} personaId={persona.id} />
    </div>
  );
}
