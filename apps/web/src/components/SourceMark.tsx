import { Icon } from './Icon';

/** Монограмма источника вместо логотипа издания; для аналитики банка — красная иконка банка. */
export function SourceMark({ mark, title }: { mark: string | null; title?: string }) {
  if (mark === null)
    return (
      <span className="source-mark source-mark--bank" title={title} aria-hidden="true">
        <Icon name="bank" size={16} />
      </span>
    );
  return (
    <span className="source-mark" title={title} aria-hidden="true">
      {mark}
    </span>
  );
}
