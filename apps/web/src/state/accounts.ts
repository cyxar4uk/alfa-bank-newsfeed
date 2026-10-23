// Демонстрационный вход по тестовым учёткам. Это не защита: учётки и пароли открыты (README, раздел
// «Тестовые учётки») и проверяются в браузере. Учётка — человек; у него может быть несколько компаний и ролей.

export interface DemoAccount {
  login: string;
  password: string;
  /** кто это — для подписи в интерфейсе */
  name: string;
  /** пользователи (компания + роль), доступные учётке; all — все тестовые пользователи */
  personas: string[] | 'all';
}

export const DEMO_PASSWORD = 'radar2026';

export const DEMO_ACCOUNTS: DemoAccount[] = [
  { login: 'expert', password: DEMO_PASSWORD, name: 'Эксперт: все тестовые компании и роли', personas: 'all' },
  {
    login: 'owner',
    password: DEMO_PASSWORD,
    name: 'Собственник топливного холдинга и гендиректор зернотрейдера',
    personas: ['p-u57706-owner', 'p-u34911-ceo'],
  },
  {
    login: 'finance',
    password: DEMO_PASSWORD,
    name: 'Финдиректор оптовика автозапчастей и казначей зернотрейдера',
    personas: ['p-u8318-cfo', 'p-u34911-tre'],
  },
  {
    login: 'horeca',
    password: DEMO_PASSWORD,
    name: 'Гендиректор поставщика общепита',
    personas: ['p-u258116-ceo'],
  },
];

export function findAccount(login: string, password: string): DemoAccount | null {
  const l = login.trim().toLowerCase();
  return DEMO_ACCOUNTS.find((a) => a.login === l && a.password === password) ?? null;
}

export function accountByLogin(login: string | null): DemoAccount | null {
  return DEMO_ACCOUNTS.find((a) => a.login === login) ?? null;
}
