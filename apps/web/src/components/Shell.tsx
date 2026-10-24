import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { Disclaimer } from './Disclaimer';
import { ErrorBoundary } from './ErrorBoundary';
import { SERVICE_NAME } from '../state/labels';
import { Icon, type IconName } from './Icon';
import { PersonaSwitcher } from './PersonaSwitcher';

export const PROTOTYPE_NOTICE =
  'Прототип для хакатона. Не является сервисом Альфа-Банка. Данные обезличены и тестовые.';

export function PrototypeNotice() {
  return <div className="prototype-notice">{PROTOTYPE_NOTICE}</div>;
}

/** Нейтральный знак макета: без логотипа банка. */
export function BrandMark() {
  return (
    <span className="brand">
      <span className="brand__mark" aria-hidden="true">
        <Icon name="radar" size={18} />
      </span>
      <span className="brand__name">
        Интернет-банк для бизнеса
        <span className="brand__badge">макет</span>
      </span>
    </span>
  );
}

// Разделы макета интернет-банка — антураж, кроме главной и нашего сервиса.
const decorative: { icon: IconName; label: string }[] = [
  { icon: 'payments', label: 'Платежи' },
  { icon: 'documents', label: 'Выписка' },
  { icon: 'accounts', label: 'Счета' },
  { icon: 'buyers', label: 'Контрагенты' },
  { icon: 'salary', label: 'Зарплатный проект' },
];

function Decorative({ icon, label }: { icon: IconName; label: string }) {
  return (
    <span className="nav__item nav__item--muted" title="В макете раздел не реализован">
      <Icon name={icon} />
      {label}
    </span>
  );
}

// Лента и карточка показывают дисклеймер сами, в своей раскладке (макет «Итог»).
const SERVICE_PAGES = new Set(['map', 'weekly', 'analyze', 'trace', 'search']);
function ownDisclaimer(pathname: string) {
  const [, radar, page] = pathname.split('/');
  return radar === 'radar' && (page === undefined || page === '' || !SERVICE_PAGES.has(page));
}

export function Shell() {
  const { pathname } = useLocation();
  return (
    <div className="app">
      <PrototypeNotice />
      <div className="layout">
        <aside className="sidebar">
          <NavLink to="/" className="sidebar__brand" aria-label="На главную">
            <BrandMark />
          </NavLink>
          <nav className="nav" aria-label="Разделы">
            <span className="nav__new" title="В макете раздел не реализован">
              <span className="nav__new-icon" aria-hidden="true">
                <Icon name="plus" size={16} />
              </span>
              Новый платёж
            </span>
            <NavLink to="/" end className="nav__item">
              <Icon name="home" />
              Главная
            </NavLink>
            {decorative.map((item) => (
              <Decorative key={item.label} {...item} />
            ))}
            <p className="nav__group">Мои сервисы</p>
            <NavLink to="/radar" className="nav__item nav__item--service">
              <Icon name="radar" />
              {SERVICE_NAME}
            </NavLink>
          </nav>
        </aside>
        <div className="main">
          <header className="topbar">
            <span className="topbar__spacer" />
            <span className="topbar__icons" aria-hidden="true">
              <Icon name="calendar" />
              <Icon name="mail" />
              <Icon name="bell" />
            </span>
            <PersonaSwitcher />
          </header>
          <main className="content">
            <ErrorBoundary key={pathname}>
              <div className="page-enter" key={pathname}>
                <Outlet />
              </div>
            </ErrorBoundary>
            {pathname.startsWith('/radar') && !ownDisclaimer(pathname) && <Disclaimer />}
          </main>
        </div>
      </div>
    </div>
  );
}
