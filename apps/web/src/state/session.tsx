import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import type { CompanyProfile, Persona } from '../api/types';
import { accountByLogin, findAccount, type DemoAccount } from './accounts';
import { useAsync } from './useAsync';

const STORAGE_KEY = 'pulse.persona';
const ACCOUNT_KEY = 'pulse.account';

export type LoginResult = 'ok' | 'wrong' | 'no-users';

interface Session {
  /** учётка, под которой вошли; null — не вошли */
  account: DemoAccount | null;
  /** пользователи (компания + роль), доступные учётке */
  personas: Persona[];
  companies: Record<string, CompanyProfile>;
  persona: Persona | null;
  company: CompanyProfile | null;
  selectPersona: (id: string) => void;
  /** вход по тестовой учётке: wrong — неверный логин или пароль; no-users — учётке не нашлось ни одной компании */
  login: (login: string, password: string) => LoginResult;
  logout: () => void;
}

const SessionContext = createContext<Session | null>(null);

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string | null) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // без хранилища вход живёт до перезагрузки
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
  const [accountLogin, setAccountLogin] = useState<string | null>(() => readStored(ACCOUNT_KEY));
  const [personaId, setPersonaId] = useState<string | null>(() => readStored(STORAGE_KEY));

  const allowedFor = useCallback(
    (account: DemoAccount | null) =>
      !account
        ? []
        : account.personas === 'all'
          ? personas
          : personas.filter((p) => (account.personas as string[]).includes(p.id)),
    [personas],
  );

  const selectPersona = useCallback((id: string) => {
    setPersonaId(id);
    store(STORAGE_KEY, id);
  }, []);

  const login = useCallback(
    (name: string, password: string): LoginResult => {
      const account = findAccount(name, password);
      if (!account) return 'wrong';
      const allowed = allowedFor(account).filter((p) => companies[p.company_id]);
      if (allowed.length === 0) return 'no-users';
      setAccountLogin(account.login);
      store(ACCOUNT_KEY, account.login);
      selectPersona(allowed[0].id);
      return 'ok';
    },
    [allowedFor, companies, selectPersona],
  );

  const logout = useCallback(() => {
    setAccountLogin(null);
    setPersonaId(null);
    store(ACCOUNT_KEY, null);
    store(STORAGE_KEY, null);
  }, []);

  const value = useMemo<Session>(() => {
    const account = accountByLogin(accountLogin);
    // Пользователи без профиля компании недоступны — иначе экраны упали бы без компании.
    const allowed = allowedFor(account).filter((p) => companies[p.company_id]);
    // Сохранённый пользователь не из этой учётки (или пропал из API) — берём первого доступного.
    const persona = allowed.find((p) => p.id === personaId) ?? allowed[0] ?? null;
    return {
      account: allowed.length > 0 ? account : null,
      personas: allowed,
      companies,
      persona,
      company: persona ? companies[persona.company_id] : null,
      selectPersona,
      login,
      logout,
    };
  }, [accountLogin, personaId, allowedFor, companies, selectPersona, login, logout]);

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
