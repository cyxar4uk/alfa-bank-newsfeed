import { Icon } from './Icon';

/** Подпись на экранах сервиса (макет «Итог»). */
export function PrototypeNote() {
  return (
    <p className="prototype-note">
      <Icon name="info" size={14} />
      Прототип для хакатона. Не является сервисом Альфа-Банка. Данные обезличены и тестовые.
    </p>
  );
}
