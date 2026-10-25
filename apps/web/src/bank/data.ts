// Антураж главной интернет-банка: счета и платежи. Не из API, только для макета.

export interface Account {
  name: string;
  number: string;
  balance: number;
  currency: 'RUB' | 'USD' | 'CNY' | 'KZT';
}

export interface Payment {
  date: string;
  counterparty: string;
  purpose: string;
  amount: number;
  currency: 'RUB' | 'USD' | 'CNY' | 'KZT';
  status: 'Исполнен' | 'В обработке' | 'На подписи';
}

interface BankView {
  accounts: Account[];
  payments: Payment[];
}

// Суммы — тестовые, для антуража; контрагенты — обезличенные id из данных кейса.
const views: Record<string, BankView> = {
  U_8318: {
    accounts: [
      { name: 'Расчётный счёт', number: '40702 810 ··· 8318', balance: 412_806_330.15, currency: 'RUB' },
      { name: 'Кредитная линия, доступный остаток', number: '45207 810 ··· 8318', balance: 750_000_000, currency: 'RUB' },
    ],
    payments: [
      { date: '2026-10-23', counterparty: 'Поставщик автозапчастей', purpose: 'Поставка автозапчастей по договору группы', amount: -184_220_000, currency: 'RUB', status: 'На подписи' },
      { date: '2026-10-22', counterparty: 'Поставщик комплектующих', purpose: 'Поставка комплектующих, спецификация 41', amount: -26_900_450, currency: 'RUB', status: 'Исполнен' },
      { date: '2026-10-22', counterparty: 'Покупатель', purpose: 'Оплата по договору поставки', amount: 312_450_000, currency: 'RUB', status: 'Исполнен' },
      { date: '2026-10-21', counterparty: 'Банк', purpose: 'Проценты по кредитной линии за октябрь', amount: -9_870_400, currency: 'RUB', status: 'Исполнен' },
    ],
  },
  U_57706: {
    accounts: [
      { name: 'Расчётный счёт', number: '40702 810 ··· 7706', balance: 1_964_120_000.4, currency: 'RUB' },
      { name: 'Депозит', number: '42106 810 ··· 7706', balance: 5_000_000_000, currency: 'RUB' },
      { name: 'Валютный счёт', number: '40702 398 ··· 7706', balance: 1_240_000_000, currency: 'KZT' },
    ],
    payments: [
      { date: '2026-10-23', counterparty: 'Покупатель, Казахстан', purpose: 'Оплата по контракту на поставку топлива', amount: 860_000_000, currency: 'KZT', status: 'Исполнен' },
      { date: '2026-10-22', counterparty: 'Банк', purpose: 'Проценты по депозиту за октябрь', amount: 58_300_000, currency: 'RUB', status: 'Исполнен' },
      { date: '2026-10-21', counterparty: 'Лизингодатель', purpose: 'Лизинговый платёж, бензовозы', amount: -4_120_500, currency: 'RUB', status: 'Исполнен' },
    ],
  },
  U_34911: {
    accounts: [
      { name: 'Расчётный счёт', number: '40702 810 ··· 4911', balance: 286_410_900.7, currency: 'RUB' },
      { name: 'Валютный счёт', number: '40702 840 ··· 4911', balance: 14_620_000, currency: 'USD' },
    ],
    payments: [
      { date: '2026-10-23', counterparty: 'Покупатель, ОАЭ', purpose: 'Оплата по контракту на поставку пшеницы', amount: 4_380_000, currency: 'USD', status: 'В обработке' },
      { date: '2026-10-22', counterparty: 'Сельхозпроизводитель', purpose: 'Закупка пшеницы 4 класса, партия 18', amount: -96_400_000, currency: 'RUB', status: 'Исполнен' },
      { date: '2026-10-21', counterparty: 'Перевозчик', purpose: 'Доставка зерна до порта, октябрь', amount: -21_760_000, currency: 'RUB', status: 'Исполнен' },
    ],
  },
  U_258116: {
    accounts: [
      { name: 'Расчётный счёт', number: '40702 810 ··· 8116', balance: 118_330_640.2, currency: 'RUB' },
      { name: 'Валютный счёт', number: '40702 156 ··· 8116', balance: 6_400_000, currency: 'CNY' },
    ],
    payments: [
      { date: '2026-10-23', counterparty: 'Ресторан', purpose: 'Оплата поставки продуктов, накладные 9921–9934', amount: 1_284_000, currency: 'RUB', status: 'Исполнен' },
      { date: '2026-10-23', counterparty: 'Контейнерный терминал', purpose: 'Терминальная обработка контейнеров', amount: -8_960_000, currency: 'RUB', status: 'На подписи' },
      { date: '2026-10-22', counterparty: 'Арендодатель склада', purpose: 'Аренда складского комплекса, октябрь', amount: -44_100_000, currency: 'RUB', status: 'Исполнен' },
      { date: '2026-10-22', counterparty: 'Поставщик, Китай', purpose: 'Предоплата за партию товара', amount: -1_900_000, currency: 'CNY', status: 'В обработке' },
    ],
  },
};

export function bankView(companyId: string): BankView {
  return views[companyId] ?? { accounts: [], payments: [] };
}
