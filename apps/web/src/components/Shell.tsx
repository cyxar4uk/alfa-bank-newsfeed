import { NavLink, Outlet } from 'react-router-dom';
import { SERVICE_NAME } from '../state/labels';
import { Icon, type IconName } from './Icon';
import { PersonaSwitcher } from './PersonaSwitcher';

export function PrototypeNotice() {
  return (
    <div className="prototype-notice">
      Прототип для хакатона, данные тестовые. Это не интернет-банк и не сервис Альфа-Банка.
    </div>
  );
}

export function BrandMark() {
  return (
    <span className="brand">
      <span className="brand__mark" aria-hidden="true" />
      <span className="brand__name">Бизнес-банк</span>
      <span className="brand__badge">прототип</span>
    </span>
  );
}

// Разделы макета интернет-банка — антураж, кроме главной и нашего сервиса.
const decorative: { icon: IconName; label: string }[] = [
  { icon: 'accounts', label: 'Счета' },
  { icon: 'payments', label: 'Платежи' },
  { icon: 'salary', label: 'Зарплатный проект' },
  { icon: 'documents', label: 'Документы' },
];

export function Shell() {
  return (
    <div className="app">
      <PrototypeNotice />
      <div className="layout">
        <aside className="sidebar">
          <NavLink to="/" className="sidebar__brand" aria-label="На главную">
            <BrandMark />
          </NavLink>
          <nav className="nav" aria-label="Разделы">
            <NavLink to="/" end className="nav__item">
              <Icon name="home" />
              Главная
            </NavLink>
            <NavLink to="/radar" className="nav__item nav__item--service">
              <Icon name="pulse" />
              {SERVICE_NAME}
              <span className="nav__hint">что изменилось для вас</span>
            </NavLink>
            {decorative.map((item) => (
              <span key={item.label} className="nav__item nav__item--muted" title="В прототипе раздел не реализован">
                <Icon name={item.icon} />
                {item.label}
              </span>
            ))}
          </nav>
        </aside>
        <div className="main">
          <header className="topbar">
            <PersonaSwitcher />
          </header>
          <main className="content">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
