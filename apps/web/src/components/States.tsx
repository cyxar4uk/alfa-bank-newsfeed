import type { ReactNode } from 'react';
import { Icon } from './Icon';

export function Skeleton({ width = '100%', height = 14 }: { width?: number | string; height?: number }) {
  return <span className="skeleton" style={{ width, height }} aria-hidden="true" />;
}

export function ErrorState({ title, error, onRetry }: { title: string; error?: Error; onRetry: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <Icon name="warning" size={24} />
      <div>
        <p className="state__title">{title}</p>
        {error && <p className="state__text">{error.message}. Попробуйте ещё раз.</p>}
      </div>
      <button className="btn btn--secondary" type="button" onClick={onRetry}>
        <Icon name="refresh" size={16} />
        Повторить
      </button>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      {children && <div className="state__text">{children}</div>}
    </div>
  );
}
