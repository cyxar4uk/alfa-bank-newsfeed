import { useState, type FormEvent } from 'react';
import { NavLink, useNavigate, useSearchParams } from 'react-router-dom';
import { Icon } from './Icon';

/** Шапка сервиса «Новости»: название, вкладки «Лента» и «Источники», поиск по новостям (макет A+). */
export function ServiceTabs() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [q, setQ] = useState(() => params.get('q') ?? '');
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (q.trim()) navigate(`/radar/search?q=${encodeURIComponent(q.trim())}`);
  }
  return (
    <div className="service-head">
      <p className="service-head__name">Новости</p>
      <nav className="tabs" aria-label="Разделы сервиса">
        <NavLink to="/radar" end className="tabs__item">
          Лента
        </NavLink>
        <NavLink to="/radar/sources" className="tabs__item">
          Источники
        </NavLink>
      </nav>
      <form className="service-search" role="search" onSubmit={onSubmit}>
        <Icon name="search" size={18} />
        <label htmlFor="service-search" className="visually-hidden">
          Поиск по новостям
        </label>
        <input id="service-search" type="search" placeholder="Поиск по новостям" value={q} onChange={(e) => setQ(e.target.value)} />
      </form>
    </div>
  );
}
