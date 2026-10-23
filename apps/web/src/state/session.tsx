import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import type { CompanyProfile, Persona } from '../api/types';
import { useAsync } from './useAsync';

const STORAGE_KEY = 'pulse.persona';

interface Session {
  personas: Persona[];
  companies: Record<string, CompanyProfile>;
  persona: Persona | null;
  company: CompanyProfile | null;
  selectPersona: (id: string | null) => void;
}

const SessionContext = createContext<Session | null>(null);

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

async function loadDirectory(signal: AbortSignal) {
  const personas = await api.personas(signal);
  const ids = [...new Set(personas.map((p) => p.company_id))];
  const list = await Promise.all(ids.map((id) => api.company(id, signal)));
  // В интерфейсе компания подписана коротко («Оптовик автозапчастей, Москва»): подпись из пользователя API
  // главнее длинного имени по ОКВЭД из профиля.
  const label = new Map<string, string>();
  for (const p of personas) if (p.company_name && !label.has(p.company_id)) label.set(p.company_id, p.company_name);
  const companies = list.map((c) => ({ ...c, display_name: label.get(c.id) ?? c.display_name }));
  return { personas, companies: Object.fromEntries(companies.map((c) => [c.id, c])) };
}

export function useDirectory() {
  return useAsync(loadDirectory, 'directory');
}

export function SessionProvider({
  personas,
  companies,
  children,
}: {
  personas: Persona[];
  companies: Record<string, CompanyProfile>;
  children: ReactNode;
}) {
  const [personaId, setPersonaId] = useState<string | null>(readStored);

  const selectPersona = useCallback((id: string | null) => {
    setPersonaId(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // без хранилища выбор живёт до перезагрузки
    }
  }, []);

  const value = useMemo<Session>(() => {
    const found = personas.find((p) => p.id === personaId) ?? null;
    const company = found ? (companies[found.company_id] ?? null) : null;
    // Пользователь без профиля компании считается невыбранным — уходим на вход, а не падаем.
    const persona = company ? found : null;
    return {
      personas,
      companies,
      persona,
      company,
      selectPersona,
    };
  }, [personas, companies, personaId, selectPersona]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession вне SessionProvider');
  return ctx;
}

/** Для экранов внутри оболочки: пользователь уже выбран. */
export function useCurrentUser() {
  const { persona, company } = useSession();
  if (!persona || !company) throw new Error('Пользователь не выбран');
  return { persona, company };
}
