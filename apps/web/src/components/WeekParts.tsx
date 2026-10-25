import type { Dynamics, RiskStrength } from '../api/types';
import { daysLabel, DYNAMICS_LABEL, STRENGTH_FILLED, STRENGTH_LABEL, type Day } from '../state/week';

/** Мини-график новостей по дням: столбик на день, пустой день — чёрточка. С подписями дней — на карте. */
export function Spark({ days, weekdays = false }: { days: Day[]; weekdays?: boolean }) {
  const max = Math.max(1, ...days.map((d) => d.n));
  return (
    <span className={`spark${weekdays ? ' spark--days' : ''}`} role="img" aria-label={daysLabel(days)}>
      <span className="spark__bars" aria-hidden="true">
        {days.map((d, i) => (
          <i key={i} className={d.n > 0 ? 'is-on' : undefined} style={d.n > 0 ? { height: `${Math.max(18, (d.n / max) * 100)}%` } : undefined} />
        ))}
      </span>
      {weekdays && (
        <span className="spark__days" aria-hidden="true">
          {days.map((d, i) => (
            <b key={i}>{d.letter}</b>
          ))}
        </span>
      )}
    </span>
  );
}

/** Динамика сюжета: «Усилился», «Появился» — тёплая метка, «Утих» и «Держится» — серая. */
export function DynamicsTag({ dynamics }: { dynamics: Dynamics }) {
  return <span className={`tag tag--${dynamics === 'appeared' || dynamics === 'grew' ? 'warm' : 'calm'}`}>{DYNAMICS_LABEL[dynamics]}</span>;
}

/** Метка «Сейчас» на карте: тон по смыслу слова — рост и новое тёплые, укрепление рубля синее, прочее серое. */
export function NowTag({ tag }: { tag: string }) {
  const t = tag.toLowerCase();
  const tone = /креп/.test(t) ? 'info' : /(дорож|раст|нов|слаб|срок|усил)/.test(t) ? 'warm' : 'calm';
  return <span className={`tag tag--${tone}`}>{tag}</span>;
}

/** Сила влияния: три чёрточки и слово. */
export function StrengthMark({ strength }: { strength: RiskStrength }) {
  return (
    <span className="strength">
      <span className="visually-hidden">Сила влияния: </span>
      <span className="strength__bar strength__bar--dash" aria-hidden="true">
        {[1, 2, 3].map((n) => (
          <i key={n} className={n <= STRENGTH_FILLED[strength] ? 'is-on' : undefined} />
        ))}
      </span>
      <span className="strength__word">{STRENGTH_LABEL[strength]}</span>
    </span>
  );
}

/** Переключатель из двух-трёх вариантов (За день / За неделю, Смотреть как …). */
export function ChipSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="chip-switch" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className="chip" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
