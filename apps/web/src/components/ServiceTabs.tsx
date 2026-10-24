import { NavLink } from 'react-router-dom';
import { SERVICE_NAME } from '../state/labels';

/** Шапка сервиса: название и разделы. Сводки недели в API пока нет — вкладки нет. */
export function ServiceTabs() {
  return (
    <div className="service-head">
      <p className="service-head__name">{SERVICE_NAME}</p>
      <nav className="tabs" aria-label="Разделы сервиса">
        <NavLink to="/radar" end className="tabs__item">
          Сводка
        </NavLink>
        <NavLink to="/radar/map" className="tabs__item">
          К чему уязвима компания
        </NavLink>
        <NavLink to="/radar/analyze" className="tabs__item">
          Своя новость
        </NavLink>
      </nav>
    </div>
  );
}
