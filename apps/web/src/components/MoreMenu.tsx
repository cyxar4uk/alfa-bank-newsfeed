import { useEffect, useId, useRef, useState } from 'react';
import type { CardMenuItem } from '../state/screens';

/** Меню «Ещё ⋯»: все нецелевые действия карточки, чтобы на экране была одна главная кнопка. */
export function MoreMenu({ items, onPick }: { items: CardMenuItem[]; onPick: (id: CardMenuItem['id']) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('focusin', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('focusin', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="more" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="more__button"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        Ещё ⋯
      </button>
      {open && (
        <ul className="more__menu" id={menuId}>
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="more__item"
                onClick={() => {
                  setOpen(false);
                  buttonRef.current?.focus();
                  onPick(item.id);
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
