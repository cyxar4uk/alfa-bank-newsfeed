import { useId, useState } from 'react';
import type { Feature, Origin, Source, Statement } from '../api/types';
import { bankConflictOf, confidenceLabel, displayOrigin, featureText, formatDate, originHint, originLabel, sourcePage } from '../state/labels';
import { Icon, type IconName } from './Icon';

export interface RefIndex {
  sources: Record<string, Source>;
  features: Record<string, Feature>;
}

const originIcon: Record<Origin, IconName> = {
  fact: 'fact',
  data: 'data',
  bank: 'bank',
  ai: 'model',
  estimate: 'calc',
  offer: 'offer',
  hypothesis: 'hypothesis',
};

export function OriginTag({ origin }: { origin: Origin }) {
  return (
    <span className={`origin-tag origin-tag--${origin}`} title={originHint[origin]}>
      <Icon name={originIcon[origin]} size={16} />
      {originLabel[origin]}
    </span>
  );
}

export function SourceView({ source }: { source: Source }) {
  const page = sourcePage(source);
  return (
    <div className={`ref ref--${source.kind === 'alfa_analytics' ? 'bank' : 'news'}`}>
      <p className="ref__head">
        <span className="ref__publisher">
          {source.publisher ?? (source.kind === 'alfa_analytics' ? 'Аналитика Альфа-Банка' : 'Новость')}
        </span>
        {source.published_at && <time dateTime={source.published_at}>{formatDate(source.published_at)}</time>}
      </p>
      <p className="ref__title">
        {source.title}
        {page && <span className="ref__page">, стр. {page}</span>}
      </p>
      {source.fragment && <blockquote className="ref__fragment">{source.fragment}</blockquote>}
      {source.url ? (
        <a className="ref__link" href={source.url} target="_blank" rel="noreferrer">
          Открыть первоисточник
          <Icon name="external" size={14} />
        </a>
      ) : (
        <p className="ref__note">
          {source.kind === 'alfa_analytics'
            ? 'Материал аналитики банка из пакета кейса, публичной ссылки нет'
            : 'Ссылки на публикацию нет'}
        </p>
      )}
    </div>
  );
}

export function FeatureView({ feature }: { feature: Feature }) {
  return (
    <div className="ref ref--feature">
      <p className="ref__head">
        <span className="ref__publisher">Признак компании</span>
        <span>{feature.source === 'dataset' ? 'из данных банка' : 'вычислен по данным банка'}</span>
      </p>
      <p className="ref__title">
        {feature.label}: {featureText(feature)}
      </p>
    </div>
  );
}

function RefList({ refs, index }: { refs: string[]; index: RefIndex }) {
  return (
    <div className="refs">
      {refs.map((ref) => {
        const source = index.sources[ref];
        if (source) return <SourceView key={ref} source={source} />;
        const feature = index.features[ref];
        if (feature) return <FeatureView key={ref} feature={feature} />;
        return (
          <p key={ref} className="ref ref--missing">
            Источник {ref} не найден в ответе
          </p>
        );
      })}
    </div>
  );
}

function refsCount(n: number) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} источник`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} источника`;
  return `${n} источников`;
}

/** В печати раскрыть источник нельзя — показываем номера из списка источников. */
function Footnote({ refs, footnotes }: { refs: string[]; footnotes: Record<string, number> }) {
  const numbers = [...new Set(refs.map((r) => footnotes[r]).filter((n): n is number => n !== undefined))].sort((a, b) => a - b);
  if (numbers.length === 0) return null;
  return <sup className="stmt__footnote print-only"> [{numbers.join(', ')}]</sup>;
}

/** Утверждение с меткой происхождения и раскрываемыми источниками. */
export function StatementItem({
  statement,
  index,
  caption,
  footnotes,
}: {
  statement: Statement;
  index: RefIndex;
  /** подпись роли утверждения в блоке, например «Рынок» */
  caption?: string;
  /** номера источников для печатной версии: id источника → номер в списке */
  footnotes?: Record<string, number>;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const { refs, confidence } = statement;
  const origin = displayOrigin(statement.origin, confidence);
  const conflict = bankConflictOf(statement);
  const conflictSources = [
    ...new Set(
      (conflict?.refs ?? [])
        .map((r) => index.sources[r])
        .filter(Boolean)
        .map((s) =>
          [s.title, sourcePage(s) ? `стр. ${sourcePage(s)}` : null, s.published_at ? formatDate(s.published_at) : null]
            .filter(Boolean)
            .join(', '),
        ),
    ),
  ];

  return (
    <li className={`stmt stmt--${origin}`}>
      <div className="stmt__meta">
        {caption && <span className="stmt__caption">{caption}</span>}
        <OriginTag origin={origin} />
        {(origin === 'ai' || origin === 'hypothesis') && confidence && (
          <span className="stmt__confidence">{confidenceLabel[confidence]}</span>
        )}
      </div>
      {conflict && (
        <p className="stmt__conflict">
          <Icon name="warning" size={16} />
          <span>
            Расходится с позицией Альфа-Банка: {conflict.text}
            {conflictSources.length > 0 && (
              <span className="stmt__conflict-src">
                {' '}
                ({conflictSources.join('; ')})
              </span>
            )}
          </span>
        </p>
      )}
      <p className="stmt__text">
        {statement.text}
        {footnotes && <Footnote refs={refs} footnotes={footnotes} />}
      </p>
      {statement.check && (statement.check.confirm || statement.check.refute) && (
        <dl className="stmt__check">
          {statement.check.confirm && (
            <div>
              <dt>Подтвердит</dt>
              <dd>{statement.check.confirm}</dd>
            </div>
          )}
          {statement.check.refute && (
            <div>
              <dt>Опровергнет</dt>
              <dd>{statement.check.refute}</dd>
            </div>
          )}
        </dl>
      )}
      {refs.length > 0 ? (
        <button
          type="button"
          className="stmt__toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Скрыть источники' : `На чём основано: ${refsCount(refs.length)}`}
          <Icon name="chevronDown" size={14} className={open ? 'flip' : undefined} />
        </button>
      ) : (
        <p className={`stmt__no-refs ${origin === 'fact' || origin === 'bank' ? 'stmt__no-refs--warn' : ''}`}>
          {origin === 'ai' || origin === 'hypothesis'
            ? 'Источника нет — общее рассуждение модели'
            : origin === 'estimate'
              ? 'Допущение сервиса, источника нет'
              : origin === 'data'
                ? 'Из данных банка о компании, без ссылки на отдельный признак'
                : 'Ссылки на источник нет — утверждение не проверено'}
        </p>
      )}
      <div id={panelId} hidden={!open}>
        {open && <RefList refs={refs} index={index} />}
      </div>
    </li>
  );
}

export function StatementList({
  items,
  index,
  footnotes,
}: {
  items: Statement[];
  index: RefIndex;
  footnotes?: Record<string, number>;
}) {
  return (
    <ul className="stmt-list">
      {items.map((s, i) => (
        <StatementItem key={`${i}-${s.text}`} statement={s} index={index} footnotes={footnotes} />
      ))}
    </ul>
  );
}
