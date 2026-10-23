import { NavLink } from 'react-router-dom';

/** Разделы сервиса: брифинг, карта чувствительности, сводка недели. */
export function ServiceTabs() {
  return (
    <nav className="tabs" aria-label="Разделы сервиса">
      <NavLink to="/radar" end className="tabs__item">
        Брифинг
      </NavLink>
      <NavLink to="/radar/map" className="tabs__item">
        К чему уязвима компания
      </NavLink>
      <NavLink to="/radar/weekly" className="tabs__item">
        Сводка недели
      </NavLink>
    </nav>
  );
}
