import { useNavigate } from 'react-router-dom';
import { BrandMark, PrototypeNotice } from '../components/Shell';
import { featureText, roleLabel } from '../state/labels';
import { useSession } from '../state/session';

// Признаки из контракта, которые есть у любой компании: отрасль, выручка, регион.
const PREVIEW_FEATURES = ['feat:MAINOKVED_CODE', 'feat:REVENUE_COMPANY', 'feat:REGION'];

export function LoginPage() {
  const { personas, companies, selectPersona } = useSession();
  const navigate = useNavigate();

  return (
    <div className="app">
      <PrototypeNotice />
      <div className="login">
        <div className="login__head">
          <BrandMark />
          <h1 className="login__title">Вход в интернет-банк</h1>
          <p className="login__lead">
            Выберите тестового пользователя: компанию и роль. Компании обезличены, у каждой свои признаки из данных
            банка — от них и от роли зависит, какие события вы увидите.
          </p>
        </div>
        <ul className="login__list">
          {personas.map((p) => {
            const company = companies[p.company_id];
            if (!company) return null;
            return (
              <li key={p.id} className="card login-card">
                <h2 className="login-card__title">
                  <span className="login-card__role">{roleLabel[p.role]}</span>
                  <span className="login-card__company">{company.display_name}</span>
                </h2>
                <dl className="login-card__features">
                  {company.features
                    .filter((f) => PREVIEW_FEATURES.includes(f.id))
                    .map((f) => (
                      <div key={f.id}>
                        <dt>{f.label}</dt>
                        <dd>{featureText(f)}</dd>
                      </div>
                    ))}
                </dl>
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={() => {
                    selectPersona(p.id);
                    navigate('/');
                  }}
                >
                  Войти
                  <span className="visually-hidden">
                    {' '}
                    как {roleLabel[p.role].toLowerCase()}, {company.display_name}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
