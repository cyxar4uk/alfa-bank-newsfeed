import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { roleLabel } from '../state/labels';
import { useCurrentUser, useSession } from '../state/session';
import { Icon } from './Icon';

/** Переключатель компании и роли — на всех экранах; смена сразу перестраивает брифинг. */
export function PersonaSwitcher() {
  const { personas, companies, selectPersona, account, logout } = useSession();
  const { persona, company } = useCurrentUser();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    // Фокус ушёл за пределы меню (Tab) — закрываем.
    const onFocus = (e: FocusEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    document.addEventListener('focusin', onFocus);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('focusin', onFocus);
    };
  }, [open]);

  // Только компании, в которых у человека из учётки есть роль.
  const groups = Object.values(companies)
    .map((c) => ({ company: c, personas: personas.filter((p) => p.company_id === c.id) }))
    .filter((g) => g.personas.length > 0);

  return (
    <div className="switcher" ref={rootRef}>
      <span className="switcher__caption">Вы вошли как</span>
      <button
        ref={buttonRef}
        type="button"
        className="switcher__button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="user" />
        <span className="switcher__who">
          <span className="switcher__company">{company.display_name}</span>
          <span className="switcher__role">{roleLabel[persona.role]}</span>
        </span>
        <Icon name="chevronDown" size={16} />
      </button>
      {open && (
        <div className="switcher__menu" id={listId}>
          <p className="switcher__menu-title">{account?.name ?? 'Сменить компанию или роль'}</p>
          {groups.map((g) => (
            <div key={g.company.id} className="switcher__group">
              <p className="switcher__group-name">{g.company.display_name}</p>
              {g.personas.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="switcher__option"
                  aria-current={p.id === persona.id}
                  onClick={() => {
                    selectPersona(p.id);
                    setOpen(false);
                    buttonRef.current?.focus();
                  }}
                >
                  {roleLabel[p.role]}
                  {p.id === persona.id && <Icon name="check" size={16} />}
                </button>
              ))}
            </div>
          ))}
          <button
            type="button"
            className="switcher__exit"
            onClick={() => {
              logout();
              navigate('/login');
            }}
          >
            Выйти
          </button>
        </div>
      )}
    </div>
  );
}
