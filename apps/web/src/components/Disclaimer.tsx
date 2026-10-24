import { Icon } from './Icon';

// Тот же текст, что api.contract.DISCLAIMER: в ленте и в карточке он должен совпадать.
export const DISCLAIMER =
  'Материалы носят информационный характер и не являются инвестиционной рекомендацией. Решения принимайте с учётом собственного анализа.';

/** Обязательный дисклеймер (Q49 организаторов). Текст из API, если он пришёл с разбором. */
export function Disclaimer({ text }: { text?: string | null }) {
  return (
    <p className="disclaimer" role="note">
      <Icon name="info" size={16} />
      <span>{text || DISCLAIMER}</span>
    </p>
  );
}
