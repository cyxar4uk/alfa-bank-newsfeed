import { Link } from 'react-router-dom';
import { bankView } from '../bank/data';
import { Money } from '../bank/Money';
import { BankBadge } from '../components/FeedParts';
import { factorIcon } from '../components/factorIcon';
import { Icon, type IconName } from '../components/Icon';
import { Skeleton } from '../components/States';
import { TOP_EVENTS, useBriefing } from '../state/briefing';
import { formatDate, SERVICE_NAME } from '../state/labels';
import { eventPath } from '../state/routes';
import { useCurrentUser } from '../state/session';

// Антураж главной интернет-банка: быстрые действия и строка дел — без действий в макете.
const QUICK_ACTIONS: { icon: IconName; label: string }[] = [
  { icon: 'payments', label: 'Платёж по реквизитам' },
  { icon: 'documents', label: 'Выписка по счёту' },
  { icon: 'salary', label: 'Зарплатная ведомость' },
  { icon: 'card', label: 'Корпоративные карты' },
];

const TASKS: { label: string; count: number; urgent?: boolean }[] = [
  { label: 'Оплатить', count: 1, urgent: true },
  { label: 'Подписать', count: 3 },
  { label: 'Отправить', count: 2 },
  { label: 'В работе у банка', count: 4 },
];

/** Постоянная точка входа в сервис на главной: те же главные события, что в брифинге, в том же порядке. */
function ServicePlate() {
  const { company } = useCurrentUser();
  const feed = useBriefing();
  const items = feed.status === 'ok' ? feed.data.items : [];
  const top = items.slice(0, TOP_EVENTS);

  return (
    <section className="card plate" aria-labelledby="plate-title">
      <div className="plate__head">
        <h2 className="plate__title" id="plate-title">
          <span className="plate__mark" aria-hidden="true">
            <Icon name="radar" size={20} />
          </span>
          <span>
            {SERVICE_NAME}
            <span className="plate__subtitle">Что изменилось для «{company.display_name}»</span>
          </span>
        </h2>
        <Link to="/radar" className="link-action">
          {items.length > 0 ? `Весь брифинг · ${items.length}` : 'Весь брифинг'}
        </Link>
      </div>

      {feed.status === 'loading' && (
        <ul className="plate__list" aria-busy="true" aria-label="Загружаем события">
          {Array.from({ length: TOP_EVENTS }, (_, i) => (
            <li key={i} className="plate__row plate__row--skeleton">
              <Skeleton width={40} height={40} />
              <span className="plate__skeleton-text">
                <Skeleton width="60%" height={16} />
                <Skeleton width="40%" height={12} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {feed.status === 'error' && (
        <div className="plate__state">
          <span>Не удалось загрузить события.</span>
          <button type="button" className="btn btn--secondary" onClick={feed.retry}>
            Повторить
          </button>
        </div>
      )}
      {feed.status === 'ok' && top.length === 0 && (
        <div className="plate__state">Сегодня значимых для компании событий нет.</div>
      )}
      {top.length > 0 && (
        <ul className="plate__list">
          {top.map((item) => (
            <li key={item.event_id}>
              <Link to={eventPath(item.event_id)} className="plate__row">
                <span className="icon-tile" aria-hidden="true">
                  <Icon name={factorIcon(item.factors[0]?.code ?? '')} />
                </span>
                <span className="plate__text">
                  <span className="plate__item-title">{item.event.title}</span>
                  <span className="plate__item-why">{item.relevance.reason}</span>
                </span>
                <span className="plate__aside">
                  {item.has_bank_view && <BankBadge />}
                  <span className="plate__item-date">{formatDate(item.event.date)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="plate__note">Прототип для хакатона. Данные обезличены.</p>
    </section>
  );
}

export function HomePage() {
  const { company } = useCurrentUser();
  const { accounts, payments } = bankView(company.id);

  return (
    <div className="page">
      <ul className="quick-actions" aria-label="Быстрые действия (в макете не работают)">
        {QUICK_ACTIONS.map((a) => (
          <li key={a.label} className="quick-action">
            <span className="icon-tile" aria-hidden="true">
              <Icon name={a.icon} />
            </span>
            {a.label}
          </li>
        ))}
      </ul>

      <ul className="tasks card" aria-label="Дела в работе (в макете не работают)">
        {TASKS.map((t) => (
          <li key={t.label}>
            {t.label}
            <span className={`counter ${t.urgent ? 'counter--urgent' : ''}`}>{t.count}</span>
          </li>
        ))}
      </ul>

      <ServicePlate />

      <section className="card" aria-labelledby="accounts-title">
        <h2 className="card__title" id="accounts-title">
          Счета
        </h2>
        <ul className="accounts">
          {accounts.map((a) => (
            <li key={a.number} className="account">
              <span className="account__name">{a.name}</span>
              <span className="account__balance">
                <Money amount={a.balance} currency={a.currency} />
              </span>
              <span className="account__number">{a.number}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="payments-title">
        <h2 className="card__title" id="payments-title">
          История операций
        </h2>
        <div className="table-wrap">
          <table className="table">
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
                  <td className="table__muted">{formatDate(p.date)}</td>
                  <td>
                    <span className="table__main">{p.counterparty}</span>
                    <span className="table__sub">{p.purpose}</span>
                  </td>
                  <td>
                    <span className={`status status--${p.status === 'Исполнен' ? 'done' : p.status === 'На подписи' ? 'info' : 'pending'}`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="num">
                    <Money amount={p.amount} currency={p.currency} signed />
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
