import { Link } from 'react-router-dom';
import { bankView, formatMoney } from '../bank/data';
import { BankBadge, RelevanceMeter } from '../components/FeedParts';
import { Icon } from '../components/Icon';
import { Skeleton } from '../components/States';
import { TOP_EVENTS, useBriefing } from '../state/briefing';
import { formatDate, SERVICE_NAME } from '../state/labels';
import { eventPath } from '../state/routes';
import { useCurrentUser } from '../state/session';

/** Постоянная точка входа в сервис на главной: те же главные события, что в брифинге, в том же порядке. */
function ServicePlate() {
  const { company } = useCurrentUser();
  const feed = useBriefing();
  const items = feed.status === 'ok' ? feed.data.items : [];
  const top = items.slice(0, TOP_EVENTS);

  return (
    <section className="plate" aria-labelledby="plate-title">
      <div className="plate__head">
        <div>
          <h2 className="plate__title" id="plate-title">
            <Icon name="pulse" size={22} />
            {SERVICE_NAME}
          </h2>
          <p className="plate__lead">Что изменилось для «{company.display_name}»: главные события и как они вас задевают</p>
        </div>
        <Link to="/radar" className="btn btn--on-dark">
          {items.length > 0 ? `Открыть брифинг (${items.length})` : 'Открыть брифинг'}
        </Link>
      </div>

      {feed.status === 'loading' && (
        <ol className="plate__list" aria-busy="true">
          {Array.from({ length: TOP_EVENTS }, (_, i) => (
            <li key={i} className="plate__item plate__item--skeleton">
              <Skeleton width="40%" height={12} />
              <Skeleton width="90%" height={18} />
              <Skeleton width="70%" />
            </li>
          ))}
        </ol>
      )}
      {feed.status === 'error' && (
        <div className="plate__state">
          <span>Не удалось загрузить события. Попробуйте ещё раз.</span>
          <button type="button" className="btn btn--on-dark" onClick={feed.retry}>
            Повторить
          </button>
        </div>
      )}
      {feed.status === 'ok' && top.length === 0 && (
        <div className="plate__state">Сегодня значимых для вас событий нет — загляните позже.</div>
      )}
      {top.length > 0 && (
        <ol className="plate__list">
          {top.map((item) => (
            <li key={item.event_id} className="plate__item">
              <Link to={eventPath(item.event_id)} className="plate__link">
                <span className="plate__item-top">
                  <RelevanceMeter score={item.relevance.score} />
                  {item.has_bank_view && <BankBadge />}
                </span>
                <span className="plate__item-title">{item.event.title}</span>
                <span className="plate__item-why">{item.relevance.reason}</span>
                <span className="plate__item-channel">{item.channel_text}</span>
                <span className="plate__item-date">{formatDate(item.event.date)}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function HomePage() {
  const { company } = useCurrentUser();
  const { accounts, payments } = bankView(company.id);

  return (
    <div className="page">
      <header className="page-head">
        <h1 className="page-head__title">Добрый день</h1>
        <p className="page-head__lead">{company.display_name}</p>
      </header>

      <ServicePlate />

      <section className="home-section" aria-labelledby="accounts-title">
        <h2 className="section-title" id="accounts-title">
          Счета
        </h2>
        <ul className="accounts">
          {accounts.map((a) => (
            <li key={a.number} className="account">
              <span className="account__name">{a.name}</span>
              <span className="account__balance">{formatMoney(a.balance, a.currency)}</span>
              <span className="account__number">{a.number}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="home-section" aria-labelledby="payments-title">
        <h2 className="section-title" id="payments-title">
          Последние платежи
        </h2>
        <div className="table-wrap">
          <table className="payments">
            <thead>
              <tr>
                <th scope="col">Дата</th>
                <th scope="col">Контрагент и назначение</th>
                <th scope="col">Статус</th>
                <th scope="col" className="num">
                  Сумма
                </th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={`${p.date}-${p.counterparty}-${p.amount}`}>
                  <td className="payments__date">{formatDate(p.date)}</td>
                  <td>
                    <span className="payments__who">{p.counterparty}</span>
                    <span className="payments__purpose">{p.purpose}</span>
                  </td>
                  <td>
                    <span className={`status status--${p.status === 'Исполнен' ? 'done' : 'pending'}`}>
                      {p.status}
                    </span>
                  </td>
                  <td className={`num ${p.amount > 0 ? 'payments__in' : ''}`}>
                    {formatMoney(p.amount, p.currency, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
