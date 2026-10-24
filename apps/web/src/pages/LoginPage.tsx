import { useId, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { BrandMark, PrototypeNotice } from '../components/Shell';
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from '../state/accounts';
import { useSession, type LoginResult } from '../state/session';

/** Демо-вход по тестовой учётке. Учётка — человек; у него может быть несколько компаний и ролей. */
export function LoginPage() {
  const { login } = useSession();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [result, setResult] = useState<LoginResult | null>(null);
  const failed = result === 'wrong' || result === 'no-users';
  // Номер попытки: повторная ошибка с теми же данными тоже должна прозвучать.
  const [attempt, setAttempt] = useState(0);
  const loginRef = useRef<HTMLInputElement>(null);
  const loginId = useId();
  const passwordId = useId();
  const errorId = useId();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const r = login(name, password);
    if (r === 'ok') navigate('/');
    else {
      setResult(r);
      setAttempt((n) => n + 1);
      loginRef.current?.focus();
    }
  }

  return (
    <div className="app">
      <PrototypeNotice />
      <div className="login">
        <div className="login__head">
          <BrandMark />
          <h1 className="login__title">Вход в интернет-банк</h1>
          <p className="login__lead">
            Войдите под тестовой учёткой. После входа можно переключаться между компаниями и ролями этой учётки — от них
            зависит, какие события вы увидите.
          </p>
        </div>
        <form className="card login-form" onSubmit={onSubmit} noValidate>
          <div className="analyze__field">
            <label htmlFor={loginId}>Логин</label>
            <input
              ref={loginRef}
              id={loginId}
              className="field"
              autoComplete="username"
              value={name}
              aria-invalid={failed}
              aria-describedby={failed ? errorId : undefined}
              onChange={(e) => {
                setName(e.target.value);
                setResult(null);
              }}
            />
          </div>
          <div className="analyze__field">
            <label htmlFor={passwordId}>Пароль</label>
            <input
              id={passwordId}
              className="field"
              type="password"
              autoComplete="current-password"
              value={password}
              aria-invalid={failed}
              aria-describedby={failed ? errorId : undefined}
              onChange={(e) => {
                setPassword(e.target.value);
                setResult(null);
              }}
            />
          </div>
          <div aria-live="assertive">
            {failed && (
              <p key={attempt} id={errorId} className="analyze__error">
                {result === 'wrong'
                  ? 'Неверный логин или пароль. Тестовые учётки — ниже.'
                  : 'Учётка верная, но её компаний сейчас нет в данных. Попробуйте другую учётку или зайдите позже.'}
              </p>
            )}
          </div>
          <button type="submit" className="btn btn--primary">
            Войти
          </button>
        </form>
        <details className="login-accounts">
          <summary>Тестовые учётки</summary>
          <p>
            Пароль у всех — <code>{DEMO_PASSWORD}</code>. Это демонстрационный вход, а не защита: учётки открыты.
          </p>
          <ul>
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.login}>
                <code>{a.login}</code> — {a.name}
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}
