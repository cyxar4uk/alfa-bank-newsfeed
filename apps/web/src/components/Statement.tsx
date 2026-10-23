import { useId, useState } from 'react';
import type { Feature, Origin, Source, Statement } from '../api/types';
import { confidenceLabel, featureValue, formatDate, originHint, originLabel } from '../state/labels';
import { Icon, type IconName } from './Icon';

export interface RefIndex {
  sources: Record<string, Source>;
  features: Record<string, Feature>;
}

const originIcon: Record<Origin, IconName> = {
  fact: 'fact',
  data: 'accounts',
  bank: 'bank',
  ai: 'model',
  estimate: 'calc',
  offer: 'bank',
};

export function OriginTag({ origin }: { origin: Origin }) {
  return (
    <span className={`origin-tag origin-tag--${origin}`} title={originHint[origin]}>
      <Icon name={originIcon[origin]} size={14} />
      {originLabel[origin]}
    </span>
  );
}

/** Номер страницы из id вида src:alfa:<материал>#p<стр.> */
function pageOf(id: string): string | null {
  const m = /#p(\d+)$/.exec(id);
  return m ? m[1] : null;
}

export function SourceView({ source }: { source: Source }) {
  const page = pageOf(source.id);
  return (
    <div className={`ref ref--${source.kind === 'alfa_analytics' ? 'bank' : 'news'}`}>
      <p className="ref__head">
        <span className="ref__publisher">{source.publisher}</span>
        <time dateTime={source.published_at}>{formatDate(source.published_at)}</time>
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
        {feature.label}: {featureValue(feature.value)}
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

/** Утверждение с меткой происхождения и раскрываемыми источниками. */
export function StatementItem({
  statement,
  index,
  caption,
}: {
  statement: Statement;
  index: RefIndex;
  /** подпись роли утверждения в блоке, например «Рынок» */
  caption?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const { origin, refs, confidence } = statement;

  return (
    <li className={`stmt stmt--${origin}`}>
      <div className="stmt__meta">
        {caption && <span className="stmt__caption">{caption}</span>}
        <OriginTag origin={origin} />
        {origin === 'ai' && confidence && <span className="stmt__confidence">{confidenceLabel[confidence]}</span>}
      </div>
      <p className="stmt__text">{statement.text}</p>
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
        <p className={`stmt__no-refs ${origin === 'ai' || origin === 'estimate' ? '' : 'stmt__no-refs--warn'}`}>
          {origin === 'ai'
            ? 'Источника нет — общее рассуждение модели'
            : origin === 'estimate'
              ? 'Допущение сервиса, источника нет'
              : 'Ссылки на источник нет — утверждение не проверено'}
        </p>
      )}
      {open && (
        <div id={panelId}>
          <RefList refs={refs} index={index} />
        </div>
      )}
    </li>
  );
}

export function StatementList({ items, index }: { items: Statement[]; index: RefIndex }) {
  return (
    <ul className="stmt-list">
      {items.map((s, i) => (
        <StatementItem key={`${i}-${s.text}`} statement={s} index={index} />
      ))}
    </ul>
  );
}
