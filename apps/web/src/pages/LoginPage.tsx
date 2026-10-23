import { useNavigate } from 'react-router-dom';
import { BrandMark, PrototypeNotice } from '../components/Shell';
import { featureValue, roleLabel } from '../state/labels';
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
            Выберите компанию и роль. Компании обезличены, у каждой свои признаки из данных банка — от них зависит,
            какие события вы увидите.
          </p>
        </div>
        <ul className="login__list">
          {Object.values(companies).map((company) => (
            <li key={company.id} className="login-company">
              <div className="login-company__info">
                <h2 className="login-company__name">{company.display_name}</h2>
                <dl className="login-company__features">
                  {company.features
                    .filter((f) => PREVIEW_FEATURES.includes(f.id))
                    .map((f) => (
                      <div key={f.id}>
                        <dt>{f.label}</dt>
                        <dd>{featureValue(f.value)}</dd>
                      </div>
                    ))}
                </dl>
              </div>
              <div className="login-company__roles">
                {personas
                  .filter((p) => p.company_id === company.id)
                  .map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className="btn btn--secondary btn--wrap"
                      onClick={() => {
                        selectPersona(p.id);
                        navigate('/');
                      }}
                    >
                      Войти как {roleLabel[p.role].toLowerCase()}
                    </button>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
