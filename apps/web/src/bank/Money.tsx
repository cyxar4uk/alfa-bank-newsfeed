import type { Account } from './data';

const symbols = { RUB: '₽', USD: '$', CNY: '¥', KZT: '₸' } as const;
const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

/** Сумма как в интернет-банке: целая часть жирная, копейки и валюта светлее. */
export function Money({
  amount,
  currency,
  signed = false,
}: {
  amount: number;
  currency: Account['currency'];
  signed?: boolean;
}) {
  const abs = Math.abs(amount);
  const whole = Math.trunc(abs);
  const cents = Math.round((abs - whole) * 100)
    .toString()
    .padStart(2, '0');
  const sign = amount < 0 ? '−' : signed ? '+' : '';
  return (
    <span className={`money ${signed && amount > 0 ? 'money--in' : ''}`}>
      <span className="money__whole">
        {sign}
        {integer.format(whole)}
      </span>
      <span className="money__rest">
        ,{cents} {symbols[currency]}
      </span>
    </span>
  );
}
