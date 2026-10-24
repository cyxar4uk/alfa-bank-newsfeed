import { useState } from 'react';
import type { Level } from '../state/news';

export type Origin = 'fact' | 'data' | 'ai' | 'bank';
import { LEVEL_LABEL } from '../state/news';
import { factorIcon } from './factorIcon';
import { Icon, type IconName } from './Icon';

const ORIGIN: Record<Origin, { icon: IconName; label: string }> = {
  fact: { icon: 'fact', label: 'Факт' },
  data: { icon: 'data', label: 'Данные' },
  ai: { icon: 'model', label: 'Модель' },
  bank: { icon: 'bank', label: 'Банк' },
};

/** Метка происхождения в начале строки: иконка + слово, без подложки (макет, Origin marker). */
export function OriginMark({ origin }: { origin: Origin }) {
  const o = ORIGIN[origin];
  return (
    <span className={`origin-mark origin-mark--${origin}`}>
      <Icon name={o.icon} size={14} />
      {o.label}
    </span>
  );
}

export function OriginLegendRow() {
  return (
    <div className="origin-legend" aria-label="Метки происхождения">
      {(['fact', 'data', 'bank', 'ai'] as Origin[]).map((o) => (
        <OriginMark key={o} origin={o} />
      ))}
    </div>
  );
}

const LEVEL_ICON: Record<Level, IconName> = { act: 'warning', watch: 'eye', info: 'info' };

/** Иконка уровня без подписи — в строке ленты перед выводом. */
export function LevelIcon({ level }: { level: Level }) {
  return (
    <>
      <Icon name={LEVEL_ICON[level]} size={16} className={`level-icon level-icon--${level}`} />
      <span className="visually-hidden">{LEVEL_LABEL[level]}: </span>
    </>
  );
}

/** Уровень вывода: важно / следить / к сведению. */
export function LevelBadge({ level }: { level: Level }) {
  return (
    <span className={`level level--${level}`}>
      <Icon name={LEVEL_ICON[level]} size={14} />
      {LEVEL_LABEL[level]}
    </span>
  );
}

/**
 * Картинка новости из источника; нет картинки или она не загрузилась — тематическая иллюстрация по фактору
 * (иконка на мягком фоне), без букв-заглушек.
 */
export function NewsThumb({ src, factor, size = 'm' }: { src: string | null; factor: string; size?: 's' | 'm' | 'l' | 'xl' }) {
  // Иллюстрация темы лежит под фото всегда: фото не загрузилось, загрузилось пустым или ещё грузится —
  // видна иллюстрация, а не серый прямоугольник.
  const [loaded, setLoaded] = useState<string | null>(null);
  return (
    <span
      className={`thumb thumb--${size} thumb--art thumb--${factorIcon(factor)}${loaded === src && src ? ' thumb--photo' : ''}`}
      aria-hidden="true"
    >
      <Icon name={factorIcon(factor)} size={size === 's' ? 18 : size === 'xl' ? 40 : 26} />
      {src && (
        <img
          key={src}
          src={src}
          alt=""
          loading="lazy"
          className={loaded === src ? 'thumb__img thumb__img--on' : 'thumb__img'}
          onLoad={(e) => e.currentTarget.naturalWidth > 1 && setLoaded(src)}
          onError={() => setLoaded(null)}
        />
      )}
    </span>
  );
}

/** Цепочка «событие → … → Вы» в одну строку; на узком экране переносится. */
export function Chain({ nodes }: { nodes: string[] }) {
  return (
    <ol className="route" aria-label="Как событие доходит до вас">
      {nodes.map((n, i) => (
        <li key={`${i}-${n}`} className="route__step">
          {i > 0 && <Icon name="arrowRight" size={12} className="route__arrow" />}
          <span className={i === nodes.length - 1 ? 'route__node route__node--you' : 'route__node'}>{n}</span>
        </li>
      ))}
    </ol>
  );
}

/** Кнопка раскрытия: шеврон вниз/вверх и понятная подпись, в потоке ленты. */
export function ExpandButton({ open, onClick, more, less }: { open: boolean; onClick: () => void; more: string; less: string }) {
  return (
    <button type="button" className="expand" aria-expanded={open} onClick={onClick}>
      {open ? less : more}
      <Icon name={open ? 'chevronUp' : 'chevronDown'} size={18} />
    </button>
  );
}
