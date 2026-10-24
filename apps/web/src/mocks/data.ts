// Тестовые данные для работы интерфейса без API.
// Компании и роли — демо-клиенты команды (числа посчитаны по данным кейса), позиция банка — пересказ материалов
// аналитики Альфа-Банка близко к тексту с адресом «материал · стр.», без дословных цитат. Подробные разборы — по
// эталонам для сверки агента; остальные пары «событие × пользователь» показывают только факты, позицию банка и связь.
// Оценки значимости и их разложение — тестовые.
import type {
  BankVsMarket,
  ExposureMap,
  SensitivityFactor,
  Strength,
  ChannelKind,
  CompanyProfile,
  Confidence,
  Estimate,
  Exposure,
  FactorRef,
  GroupImpact,
  Insight,
  Persona,
  ScoreTerm,
  Source,
  Statement,
} from '../api/types';

const fact = (text: string, refs: string[]): Statement => ({ text, origin: 'fact', refs, confidence: 'high' });
const data = (text: string, refs: string[]): Statement => ({ text, origin: 'data', refs, confidence: 'high' });
const bank = (text: string, refs: string[]): Statement => ({ text, origin: 'bank', refs, confidence: 'high' });
const est = (text: string, refs: string[] = []): Statement => ({ text, origin: 'estimate', refs });
const ai = (text: string, refs: string[], confidence: Confidence = 'medium'): Statement => ({
  text,
  origin: 'ai',
  refs,
  confidence,
});

// ─── Факторы ─────────────────────────────────────────────────────────────────

const F = {
  rate: { code: 'rate', label: 'Стоимость заёмных денег' },
  deposit: { code: 'deposit_yield', label: 'Доходность свободных денег' },
  fx: { code: 'fx', label: 'Курс валют' },
  ved: { code: 'ved_logistics', label: 'ВЭД, логистика и санкции' },
  consumer: { code: 'consumer', label: 'Потребительский спрос' },
  demand56: { code: 'demand_56', label: 'Спрос покупателей из общепита' },
  supply45: { code: 'supply_45', label: 'Поставщики запчастей' },
  supply52: { code: 'supply_52', label: 'Логистика и склады' },
  labor: { code: 'labor', label: 'Рынок труда и зарплаты' },
  gov: { code: 'gov', label: 'Госрасходы и бюджет' },
  oil: { code: 'commodity_oil', label: 'Нефть и топливо' },
  agro: { code: 'commodity_agro', label: 'Зерно и агро' },
  gold: { code: 'commodity_gold', label: 'Золото' },
  growth: { code: 'growth', label: 'Рост экономики и инвестиции' },
  inflation: { code: 'inflation', label: 'Инфляция издержек' },
  region: { code: 'region', label: 'События региона' },
  demand45: { code: 'demand_45', label: 'Спрос покупателей-оптовиков' },
  demand: { code: 'demand', label: 'Спрос покупателей' },
  supply: { code: 'supply', label: 'Поставщики' },
} satisfies Record<string, FactorRef>;

// ─── Компании ────────────────────────────────────────────────────────────────

const LOA = 'feat:CL_PRODUCT_LOA_MARK';
const DEP = 'feat:CL_PRODUCT_DEP_MARK';
const GAR = 'feat:CL_PRODUCT_GAR_MARK';
const LEA = 'feat:CL_PRODUCT_LEA_MARK';
const ZPP = 'feat:CL_PRODUCT_ZPP_MARK';
const FACTORING = 'feat:FACTORING_MARK';
const FTS = 'feat:FTS_COUNTRY_NAME';
const OKVED = 'feat:MAINOKVED_CODE';
const WORKERS = 'feat:AMOUNT_WORKERS_FNS_GRADATION';
const GROUP = 'feat:group';

export const companies: CompanyProfile[] = [
  {
    id: 'U_8318',
    display_name: 'Оптовик автозапчастей, Москва',
    features: [
      { id: OKVED, label: 'Основная деятельность', value: '45.31.1 Оптовая торговля автозапчастями', source: 'dataset' },
      { id: 'feat:REVENUE_COMPANY', label: 'Выручка', value: '35,9 млрд ₽', source: 'dataset' },
      { id: 'feat:REGION', label: 'Регион', value: 'Москва', source: 'dataset' },
      { id: LOA, label: 'Кредит в банке', value: true, source: 'dataset' },
      { id: ZPP, label: 'Зарплатный проект', value: true, source: 'dataset' },
      { id: DEP, label: 'Депозит в банке', value: false, source: 'dataset' },
      { id: GAR, label: 'Гарантии банка', value: false, source: 'dataset' },
      { id: WORKERS, label: 'Сотрудники', value: 'более 251', source: 'dataset' },
      { id: GROUP, label: 'Группа', value: '29 компаний, 55,7 млрд ₽, почти вся — автобизнес', source: 'derived', derived_from: ['GROUP_ID'] },
      { id: 'feat:group_loans', label: 'Кредиты в группе', value: 'у 12 из 29 компаний группы', source: 'derived', derived_from: ['GROUP_ID', LOA] },
      { id: 'feat:intra_group_suppliers', label: 'Закупки внутри группы', value: '43 % платежей (8,2 из 18,9 млрд ₽) — двум импортёрам группы', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:group_fts_countries', label: 'ВЭД компаний группы', value: 'ОАЭ, Индия, Китай; Китай, Турция, Камбоджа', source: 'derived', derived_from: ['GROUP_ID', 'FTS_COUNTRY_NAME'] },
      { id: 'feat:supply_45', label: 'Поставщики', value: 'оптовики запчастей — 50,9 % внешних платежей, покрытие 71 %', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:payers_coverage', label: 'Покупатели', value: 'отрасль известна у 24 % поступлений; 46 % — один плательщик вне данных банка', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:position', label: 'Положение в отрасли', value: '№ 1 по выручке из 422 компаний с ОКВЭД 45.31.1 в данных банка', source: 'derived', derived_from: [OKVED, 'feat:REVENUE_COMPANY'] },
    ],
    group: { id: 'group_133141_sb', members: ['U_92457', 'U_52177'] },
    missing: [],
  },
  {
    id: 'U_57706',
    display_name: 'Топливный оптовик в холдинге, Москва',
    features: [
      { id: OKVED, label: 'Основная деятельность', value: '46.71 Оптовая торговля топливом', source: 'dataset' },
      { id: 'feat:REVENUE_COMPANY', label: 'Выручка', value: '105,6 млрд ₽', source: 'dataset' },
      { id: 'feat:REGION', label: 'Регион', value: 'Москва', source: 'dataset' },
      { id: DEP, label: 'Депозит в банке', value: true, source: 'dataset' },
      { id: GAR, label: 'Гарантии банка', value: true, source: 'dataset' },
      { id: LEA, label: 'Лизинг', value: true, source: 'dataset' },
      { id: LOA, label: 'Кредит в банке', value: false, source: 'dataset' },
      { id: FTS, label: 'ВЭД', value: 'Киргизия, Казахстан', source: 'dataset' },
      { id: WORKERS, label: 'Сотрудники', value: '16–100', source: 'dataset' },
      { id: GROUP, label: 'Группа', value: '369 компаний, 302,7 млрд ₽: топливо, генерация, дороги, жильё', source: 'derived', derived_from: ['GROUP_ID'] },
      { id: 'feat:group_products', label: 'Продукты в группе', value: 'лизинг у 41 компании, гарантии у 7, кредит у 3', source: 'derived', derived_from: ['GROUP_ID'] },
      { id: 'feat:payments_coverage', label: 'Платежи в данных', value: 'меньше 1 % выручки', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:position', label: 'Положение в отрасли', value: '№ 1 по выручке из 661 компании с ОКВЭД 46.71 в данных банка', source: 'derived', derived_from: [OKVED, 'feat:REVENUE_COMPANY'] },
    ],
    group: { id: 'group_134402_sb', members: ['U_4909', 'U_191099', 'U_201985', 'U_122823', 'U_178740', 'U_417124'] },
    missing: [],
  },
  {
    id: 'U_34911',
    display_name: 'Зернотрейдер, Ростов-на-Дону',
    features: [
      { id: OKVED, label: 'Основная деятельность', value: '46.21 Оптовая торговля зерном, семенами и кормами', source: 'dataset' },
      { id: 'feat:REVENUE_COMPANY', label: 'Выручка', value: '53,9 млрд ₽', source: 'dataset' },
      { id: 'feat:REGION', label: 'Регион', value: 'Ростовская область', source: 'dataset' },
      { id: LOA, label: 'Кредит в банке', value: true, source: 'dataset' },
      { id: GAR, label: 'Гарантии банка', value: false, source: 'dataset' },
      { id: DEP, label: 'Депозит в банке', value: false, source: 'dataset' },
      { id: WORKERS, label: 'Сотрудники', value: '16–100', source: 'dataset' },
      { id: FTS, label: 'ВЭД', value: 'ОАЭ, Алжир, Индия', source: 'dataset' },
      { id: 'feat:fts_direction', label: 'Направление ВЭД', value: 'экспорт — оценка по отрасли и странам', source: 'derived', derived_from: [OKVED, FTS] },
      { id: 'feat:payments_gap', label: 'Платежи в данных', value: 'внутренних поступлений 0,01 млрд ₽; отрасль известна у 12 % платежей поставщикам', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:position', label: 'Положение в отрасли', value: '№ 1 по выручке из 204 компаний с ОКВЭД 46.21 в данных банка', source: 'derived', derived_from: [OKVED, 'feat:REVENUE_COMPANY'] },
    ],
    group: null,
    missing: [],
  },
  {
    id: 'U_258116',
    display_name: 'Поставщик общепита, Москва',
    features: [
      { id: OKVED, label: 'Основная деятельность', value: '46.90 Неспециализированная оптовая торговля', source: 'dataset' },
      { id: 'feat:REVENUE_COMPANY', label: 'Выручка', value: '17,4 млрд ₽', source: 'dataset' },
      { id: 'feat:REGION', label: 'Регион', value: 'Москва', source: 'dataset' },
      { id: LEA, label: 'Лизинг', value: true, source: 'dataset' },
      { id: ZPP, label: 'Зарплатный проект', value: true, source: 'dataset' },
      { id: FACTORING, label: 'Факторинг', value: false, source: 'dataset' },
      { id: GAR, label: 'Гарантии банка', value: false, source: 'dataset' },
      { id: DEP, label: 'Депозит в банке', value: false, source: 'dataset' },
      { id: WORKERS, label: 'Сотрудники', value: 'более 251', source: 'dataset' },
      { id: FTS, label: 'ВЭД', value: 'Китай, Индонезия, Узбекистан', source: 'dataset' },
      { id: 'feat:demand_56', label: 'Покупатели', value: 'рестораны и кафе — 53 % поступлений, 1 058 плательщиков', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:payers_coverage', label: 'Покрытие покупателей', value: 'отрасль известна у 66 % поступлений', source: 'derived', derived_from: ['payments'] },
      { id: 'feat:supply_52', label: 'Логистика', value: '17,5 % платежей', source: 'derived', derived_from: ['payments'] },
      { id: GROUP, label: 'Группа', value: '266 компаний, 46,2 млрд ₽', source: 'derived', derived_from: ['GROUP_ID'] },
    ],
    group: { id: 'group_134425_sb', members: [] },
    missing: [],
  },
];

// ─── Тестовые пользователи ───────────────────────────────────────────────────

export const personas: Persona[] = [
  { id: 'p-u8318-cfo', company_id: 'U_8318', role: 'cfo', name: 'Тестовый финдиректор' },
  { id: 'p-u8318-acc', company_id: 'U_8318', role: 'chief_accountant', name: 'Тестовый главбух' },
  { id: 'p-u57706-owner', company_id: 'U_57706', role: 'owner', name: 'Тестовый собственник' },
  { id: 'p-u57706-tre', company_id: 'U_57706', role: 'treasury', name: 'Тестовый казначей' },
  { id: 'p-u34911-ceo', company_id: 'U_34911', role: 'ceo', name: 'Тестовый гендиректор' },
  { id: 'p-u34911-tre', company_id: 'U_34911', role: 'treasury', name: 'Тестовый казначей' },
  { id: 'p-u258116-ceo', company_id: 'U_258116', role: 'ceo', name: 'Тестовый гендиректор' },
];

// ─── Материалы ───────────────────────────────────────────────────────────────

const ALFA = 'Аналитика Альфа-Банка';

/** Страница материала аналитики банка: id вида src:alfa:<материал>#p<стр.> */
function alfaPages(material: string, title: string, publishedAt: string, pages: number[]): Source[] {
  return pages.map((p) => ({
    id: `src:alfa:${material}#p${p}`,
    kind: 'alfa_analytics',
    title,
    publisher: ALFA,
    url: '',
    published_at: publishedAt,
  }));
}

export const sources: Record<string, Source> = Object.fromEntries(
  [
    ...alfaPages('keyrate-2026-09', 'Ключевая ставка ЦБ РФ: ставка без изменения на 14,0 %, риторика стала жестче', '2026-09-11', [1, 2, 3]),
    ...alfaPages('bondbrief-2026-09-14', 'Бонд Бриф: итоги недели', '2026-09-14', [1, 4]),
    // Дата обзора золота в материале не указана точно (7–10 сентября).
    ...alfaPages('gold-2026-08', 'Обзор рынка золота, август 2026', '2026-09-07', [2, 4]),
    ...alfaPages('macro-7m26', 'Макростатистика 7М26: данные по рынку труда не подтверждают охлаждения экономики', '2026-09-07', [1, 2, 3]),
    ...alfaPages('inflation-2026-08-31', 'Инфляция 25–31 августа: основные выводы', '2026-09-02', [1]),
    ...alfaPages('consumption-2026-08', 'Потребление на пике', '2026-08-05', [1, 3]),
    ...alfaPages('macro-1h26', 'Макростатистика 1П26: слабый рост 1П26 смещает наш прогноз роста ВВП на 0,1 % за год', '2026-07-31', [1, 2, 3, 4]),
    ...alfaPages('fi-strategy-3q26', 'Долговой рынок. Тактический взгляд на 3-й квартал 2026 г.: время собирать камни', '2026-07-22', [3, 9, 13, 24]),
    {
      id: 'src:news:grain-export',
      kind: 'news',
      title: 'Экспорт зерна: квоты, пошлины и загрузка портов юга',
      publisher: 'Новостная лента (тест)',
      url: 'https://example.org/news/grain-export',
      published_at: '2026-10-21T10:00:00+03:00',
      fragment: 'Тестовая новость для проверки интерфейса: обсуждаются параметры зерновой квоты и очереди судов в портах Азово-Черноморского бассейна.',
    } satisfies Source,
  ].map((s) => [s.id, s]),
);

const KR1 = 'src:alfa:keyrate-2026-09#p1';
const KR2 = 'src:alfa:keyrate-2026-09#p2';
const KR3 = 'src:alfa:keyrate-2026-09#p3';
const BB1 = 'src:alfa:bondbrief-2026-09-14#p1';
const BB4 = 'src:alfa:bondbrief-2026-09-14#p4';
const M7_1 = 'src:alfa:macro-7m26#p1';
const M7_2 = 'src:alfa:macro-7m26#p2';
const M7_3 = 'src:alfa:macro-7m26#p3';
const INF1 = 'src:alfa:inflation-2026-08-31#p1';
const CON1 = 'src:alfa:consumption-2026-08#p1';
const CON3 = 'src:alfa:consumption-2026-08#p3';
const H1 = 'src:alfa:macro-1h26#p1';
const H2 = 'src:alfa:macro-1h26#p2';
const H3 = 'src:alfa:macro-1h26#p3';
const H4 = 'src:alfa:macro-1h26#p4';
const FI3 = 'src:alfa:fi-strategy-3q26#p3';
const FI9 = 'src:alfa:fi-strategy-3q26#p9';
const FI13 = 'src:alfa:fi-strategy-3q26#p13';
const FI24 = 'src:alfa:fi-strategy-3q26#p24';

// ─── События ─────────────────────────────────────────────────────────────────

export interface MockEvent {
  id: string;
  title: string;
  date: string;
  primary: string;
  what: Statement[];
  bank: Statement[];
}

export const events: MockEvent[] = [
  {
    id: 'ev-keyrate',
    title: 'ЦБ сохранил ключевую ставку 14 %, риторика стала жёстче',
    date: '2026-09-11',
    primary: KR1,
    what: [
      fact('Совет директоров Банка России 11 сентября оставил ставку 14,0 %; вариант снижения не рассматривался', [KR1]),
      fact('До этого ставка снижалась: 16,0 % в январе, 14,25 % в июне, 14,0 % в июле', [KR3]),
      fact('ЦБ впервые в году указал, что проинфляционные риски выросли; устойчивая инфляция ускорилась до 5–6 %', [KR1]),
    ],
    bank: [
      bank('Банк ждал паузы 23 октября и сохранения 14,0 % до конца 2026 года — раньше ориентировался на 13,5 %; на конец 2027 года — 12,0 %', [KR1, KR2]),
      bank('ЦБ будет смотреть на корпоративное кредитование, которое растёт быстрее его прогнозов, и на бюджет', [KR1]),
    ],
  },
  {
    id: 'ev-ruble',
    title: 'Рубль слабеет: банк ждёт 87,2 ₽/$ к концу года и 93 ₽/$ к концу 2027-го',
    date: '2026-09-11',
    primary: KR2,
    what: [fact('В середине сентября курс — около 85–86 ₽ за доллар (по графику в обзоре банка)', [BB4])],
    bank: [
      bank('Рубль: 87,2 ₽/$ и 13,0 ₽/¥ на конец 2026 года, 93,0 ₽/$ и 13,8 ₽/¥ на конец 2027 года', [KR2]),
      bank('Ослабление рубля продолжит давить на непродовольственные цены', [INF1]),
    ],
  },
  {
    id: 'ev-fuel',
    title: 'Топливо: переработка сокращается, бензин дорожает',
    date: '2026-07-31',
    primary: H2,
    what: [
      fact('Выпуск нефтепродуктов в июне — минус 21,7 % к прошлому году', [H2]),
      fact('Бензин подорожал на 26 % за 12 месяцев на 27 июля', [H2]),
    ],
    bank: [
      bank('Топливный кризис — сокращение переработки и рост цен на бензин — один из главных проинфляционных рисков', [FI13, INF1]),
      bank('Прогноз нефти Urals — $63 за баррель в 2026 году и $60 в 2027-м', [H4]),
    ],
  },
  {
    id: 'ev-budget',
    title: 'Бюджет: дефицит 5,8 трлн ₽, расходы растут быстрее плана',
    date: '2026-09-11',
    primary: FI9,
    what: [
      fact('Расходы бюджета в первом полугодии выросли на 14 % к прошлому году при плане около +3 %', [FI9]),
      fact('Накопленный дефицит к августу — 5,8 трлн ₽, выше прогнозов', [KR1]),
    ],
    bank: [bank('Бюджет — главный риск для снижения ставки: если расходы расширятся, ставка останется высокой дольше', [FI9, KR1])],
  },
  {
    id: 'ev-auto',
    title: 'Авторынок: продажи уходят в минус, лимиты по автокредитам ужесточены',
    date: '2026-09-07',
    primary: M7_1,
    what: [
      fact('Продажи новых легковых автомобилей в августе — минус 7 % к июлю и к прошлому году', [M7_1]),
      fact('С 1 октября ужесточены макропруденциальные лимиты по автокредитам', [CON1]),
    ],
    bank: [bank('Автомобили — главный сегмент замедления потребления: продажи в ближайшие месяцы уйдут в минус', [CON1])],
  },
  {
    id: 'ev-consumption',
    title: 'Потребление замедляется, услуги отстают',
    date: '2026-09-07',
    primary: M7_1,
    what: [
      fact('Оборот розничной торговли вырос на 5,3 % г/г в июле после 7,3 % в июне', [M7_1]),
      fact('Потребление услуг в июне выросло лишь на 1,7 % г/г, непродовольственных товаров — на 9,8 %', [H2]),
    ],
    bank: [
      bank('Потребление на пике: в ближайшие два квартала рост существенно замедлится, в 4К26 — около нуля г/г', [CON1, CON3]),
      bank('Замедление будет постепенным: население снижает норму сбережений', [CON3]),
      bank('Розница: +3,3 % в 2026 году и +1,0 % в 2027-м', [H4]),
    ],
  },
  {
    id: 'ev-labor',
    title: 'Рынок труда не охлаждается: зарплаты +9,6 %, вакансии +12 %',
    date: '2026-09-07',
    primary: M7_2,
    what: [
      fact('Номинальные зарплаты в июне выросли на 9,6 % г/г', [M7_2]),
      fact('Вакансии за июнь–август выросли на 12 %', [M7_2]),
    ],
    bank: [bank('Данные по рынку труда не подтверждают охлаждения — главный аргумент против быстрого снижения ставки', [M7_1])],
  },
  {
    id: 'ev-bonds',
    title: 'ОФЗ: доходности около 16 %, драйверов улучшения нет',
    date: '2026-09-14',
    primary: BB1,
    what: [fact('Доходность ОФЗ 26254 — 16,2 %; корпоративные облигации AAA — 15,3 %, AA — 17,0 %', [BB1, BB4])],
    bank: [
      bank('Драйверов улучшения рынка ОФЗ на горизонте недель нет; возврат Минфина к активным размещениям может давить на рынок', [BB1]),
      bank('Для ликвидности — защитный портфель: флоатеры, короткие ОФЗ, корпоративный фикс до 3 лет', [FI3, FI24]),
    ],
  },
  {
    id: 'ev-gdp',
    title: 'ВВП почти стоит: банк понизил прогноз роста на 2026 год до 0,1 %',
    date: '2026-07-31',
    primary: H1,
    what: [fact('ВВП в первом полугодии вырос на 0,3 %, промышленность — на 0,4 %', [H1])],
    bank: [bank('Прогноз ВВП на 2026 год — 0,1 %, инвестиции — минус 4 %; главный источник роста промышленности — бюджет и госпроекты', [H1, H3])],
  },
  {
    id: 'ev-harvest',
    title: 'Недельная дефляция: урожай давит на цены продовольствия',
    date: '2026-09-02',
    primary: INF1,
    what: [fact('За неделю цены снизились на 0,01 %, с начала года +4,67 %, годовая инфляция 6,32 %; плодоовощи −1,72 % за неделю, бензин +0,91 %', [INF1])],
    bank: [
      bank('Недельная дефляция — сигнал дезинфляции; продовольствие может пойти ниже из-за сложностей с экспортом урожая; топливо — важный проинфляционный риск', [INF1]),
      bank('Рубль: 87,2 ₽/$ на конец 2026 года, 93,0 ₽/$ на конец 2027 года', [KR2]),
      bank('Выгода от высоких цен на экспорт может не реализоваться из-за логистики и санкционных рисков', [H3]),
    ],
  },
  {
    id: 'ev-gold',
    title: 'Золото: лучший месяц с января, +9,7 % за август',
    date: '2026-09-07',
    primary: 'src:alfa:gold-2026-08#p2',
    what: [fact('За август золото подорожало на 9,7 %', ['src:alfa:gold-2026-08#p2'])],
    bank: [bank('Структурно золото в сильной позиции почти при любом исходе: опоры — покупки центробанков, ETF и спрос Азии', ['src:alfa:gold-2026-08#p4'])],
  },
  {
    id: 'ev-import',
    title: 'Импорт растёт на 11 %: предложение отстаёт от спроса',
    date: '2026-07-31',
    primary: H3,
    what: [fact('Промышленность в первом полугодии выросла лишь на 0,4 %', [H1])],
    bank: [
      bank('Товарный импорт в 2026 году вырастет на 11 %: доля импорта восстанавливается на фоне ограничений внутреннего предложения', [H1, H3]),
      bank('Предложение отстаёт от спроса — отсюда рост импорта и ослабление рубля', [M7_2]),
    ],
  },
  {
    id: 'ev-export',
    title: 'Экспорт зерна: квоты, пошлины и загрузка портов',
    date: '2026-10-21',
    primary: 'src:news:grain-export',
    what: [fact('Обсуждаются параметры зерновой квоты и очереди судов в портах Азово-Черноморского бассейна', ['src:news:grain-export'])],
    bank: [],
  },
];

// ─── Лента: верх для каждой роли (по таблице демо-клиентов) ──────────────────

export interface MockFeedEntry {
  event: string;
  reason: string;
  refs: string[];
  factors: FactorRef[];
  channel: ChannelKind;
  channel_text: string;
}

/** Тестовые оценки значимости по месту в топ-5. */
export const RANK_SCORES = [0.91, 0.82, 0.73, 0.62, 0.51];

export const feeds: Record<string, MockFeedEntry[]> = {
  'p-u8318-cfo': [
    { event: 'ev-keyrate', reason: 'Кредит у вас и у 12 компаний группы — деньги останутся дорогими до конца года', refs: [LOA, 'feat:group_loans'], factors: [F.rate], channel: 'direct', channel_text: 'прямо: ваш кредит' },
    { event: 'ev-ruble', reason: '43 % платежей идут импортёрам группы — закупка дорожает вместе с курсом', refs: ['feat:intra_group_suppliers'], factors: [F.fx], channel: 'suppliers', channel_text: 'через поставщиков группы: 43 % платежей' },
    { event: 'ev-auto', reason: 'Автосалоны и автосервисы группы зависят от автокредитов', refs: [GROUP], factors: [F.consumer], channel: 'group', channel_text: 'через группу: автосалоны и автосервисы' },
    { event: 'ev-import', reason: 'Импорт запчастей идёт через компании группы', refs: ['feat:group_fts_countries'], factors: [F.ved], channel: 'suppliers', channel_text: 'через поставщиков-импортёров группы' },
    { event: 'ev-gdp', reason: 'Слабый рост экономики — слабее спрос на авто и запчасти', refs: [OKVED], factors: [F.growth], channel: 'direct', channel_text: 'прямо: своя отрасль' },
  ],
  'p-u8318-acc': [
    { event: 'ev-ruble', reason: 'Курсовые разницы и валютный контроль по закупкам у импортёров группы', refs: ['feat:intra_group_suppliers'], factors: [F.fx], channel: 'suppliers', channel_text: 'через поставщиков группы: 43 % платежей' },
    { event: 'ev-labor', reason: 'Больше 251 сотрудника: ФОТ и взносы растут быстрее плана', refs: [WORKERS, ZPP], factors: [F.labor], channel: 'direct', channel_text: 'прямо: ваш персонал' },
    { event: 'ev-keyrate', reason: 'Процентные расходы по кредиту останутся высокими в отчётности 4К26', refs: [LOA], factors: [F.rate], channel: 'direct', channel_text: 'прямо: ваш кредит' },
    { event: 'ev-import', reason: 'Импорт через группу: документы и контроль ВЭД', refs: ['feat:group_fts_countries'], factors: [F.ved], channel: 'suppliers', channel_text: 'через поставщиков-импортёров группы' },
    { event: 'ev-gdp', reason: 'Слабый рост — риск по дебиторской задолженности', refs: [OKVED], factors: [F.growth], channel: 'direct', channel_text: 'прямо: своя отрасль' },
  ],
  'p-u57706-owner': [
    { event: 'ev-budget', reason: 'Дороги, стройка и генерация группы живут на госзаказе', refs: [GROUP, GAR], factors: [F.gov], channel: 'group', channel_text: 'через группу: дорожные и жилищные строители' },
    { event: 'ev-fuel', reason: 'Ядро холдинга — оптовая торговля топливом', refs: [OKVED], factors: [F.oil], channel: 'direct', channel_text: 'прямо: своя отрасль' },
    { event: 'ev-keyrate', reason: 'Доход по вашему депозиту и дорогие деньги для стройки группы', refs: [DEP, GROUP], factors: [F.rate, F.deposit], channel: 'group', channel_text: 'через группу и ваш депозит' },
    { event: 'ev-gdp', reason: 'Инвестиции −4 %, стройка −5 %: спрос на проекты группы', refs: [GROUP], factors: [F.growth], channel: 'group', channel_text: 'через группу: строительный контур' },
    { event: 'ev-bonds', reason: 'Куда разместить ликвидность холдинга', refs: [DEP], factors: [F.deposit], channel: 'direct', channel_text: 'прямо: ваш депозит' },
  ],
  'p-u57706-tre': [
    { event: 'ev-keyrate', reason: 'Депозит в банке: высокая доходность сохранится до конца года', refs: [DEP], factors: [F.deposit], channel: 'direct', channel_text: 'прямо: ваш депозит' },
    { event: 'ev-bonds', reason: 'Куда разместить ликвидность: ОФЗ около 16 %, корпоративные AAA 15,3 %', refs: [DEP], factors: [F.deposit], channel: 'direct', channel_text: 'прямо: ваш депозит' },
    { event: 'ev-ruble', reason: 'Расчёты с Казахстаном и Киргизией', refs: [FTS], factors: [F.fx], channel: 'direct', channel_text: 'прямо: ВЭД, направление — оценка' },
    { event: 'ev-budget', reason: 'Бюджет держит ставку высокой — доход на остатки дольше', refs: [DEP], factors: [F.gov, F.deposit], channel: 'direct', channel_text: 'прямо: ваш депозит' },
    { event: 'ev-gold', reason: 'Защитный актив для свободных средств компании', refs: [DEP], factors: [F.gold], channel: 'direct', channel_text: 'прямо: ваша ликвидность' },
  ],
  'p-u34911-ceo': [
    { event: 'ev-harvest', reason: 'Своя отрасль — зерно: давление на внутренние цены', refs: [OKVED], factors: [F.agro], channel: 'direct', channel_text: 'прямо: своя отрасль' },
    { event: 'ev-ruble', reason: 'Экспорт (оценка): рублёвая выручка растёт со слабым рублём', refs: [FTS, 'feat:fts_direction'], factors: [F.fx], channel: 'direct', channel_text: 'прямо: ВЭД, экспорт — оценка' },
    { event: 'ev-export', reason: 'Экспорт в ОАЭ, Алжир, Индию: правила вывоза и порты', refs: [FTS], factors: [F.ved], channel: 'direct', channel_text: 'прямо: ВЭД' },
    { event: 'ev-fuel', reason: 'Доставка зерна до портов дорожает вместе с топливом', refs: [OKVED], factors: [F.oil], channel: 'direct', channel_text: 'прямо: логистика своей отрасли' },
    { event: 'ev-keyrate', reason: 'Кредит на оборотный капитал', refs: [LOA], factors: [F.rate], channel: 'direct', channel_text: 'прямо: ваш кредит' },
  ],
  'p-u34911-tre': [
    { event: 'ev-ruble', reason: 'Валютная выручка (экспорт — оценка): банк ждёт 87,2 → 93 ₽/$', refs: [FTS, 'feat:fts_direction'], factors: [F.fx], channel: 'direct', channel_text: 'прямо: ВЭД, экспорт — оценка' },
    { event: 'ev-keyrate', reason: 'Стоимость оборотного кредита', refs: [LOA], factors: [F.rate], channel: 'direct', channel_text: 'прямо: ваш кредит' },
    { event: 'ev-harvest', reason: 'Урожай и экспорт: сроки поступления выручки', refs: [OKVED], factors: [F.agro], channel: 'direct', channel_text: 'прямо: своя отрасль' },
    { event: 'ev-import', reason: 'Рост импорта давит на рубль', refs: [FTS], factors: [F.fx], channel: 'direct', channel_text: 'прямо: ВЭД' },
    { event: 'ev-bonds', reason: 'Ориентир доходности, если появятся свободные средства', refs: [], factors: [F.deposit], channel: 'direct', channel_text: 'прямо: свободные средства' },
  ],
  'p-u258116-ceo': [
    { event: 'ev-consumption', reason: 'Рестораны и кафе дают 53 % поступлений', refs: ['feat:demand_56'], factors: [F.demand56, F.consumer], channel: 'buyers', channel_text: 'через покупателей: рестораны и кафе, 53 % поступлений' },
    { event: 'ev-ruble', reason: 'Импорт из Китая и Индонезии дорожает', refs: [FTS], factors: [F.fx], channel: 'direct', channel_text: 'прямо: ВЭД, импорт — оценка' },
    { event: 'ev-labor', reason: 'Зарплаты растут у вас и у ресторанов-покупателей', refs: [WORKERS, 'feat:demand_56'], factors: [F.labor], channel: 'buyers', channel_text: 'у вас и через покупателей-рестораны' },
    { event: 'ev-fuel', reason: 'Логистика — 17,5 % платежей, топливо дорожает', refs: ['feat:supply_52'], factors: [F.supply52, F.oil], channel: 'suppliers', channel_text: 'через поставщиков: логистика, 17,5 % платежей' },
    { event: 'ev-import', reason: 'Импорт растёт: конкуренция и закупочные цены', refs: [FTS], factors: [F.ved], channel: 'direct', channel_text: 'прямо: ВЭД' },
  ],
};

/** Сводка «что изменилось для вас» — 2–3 предложения на пользователя. */
export const summaries: Record<string, Statement[]> = {
  'p-u8318-cfo': [
    ai('Деньги останутся дорогими до конца года: банк ждёт ставку 14 %, а кредит есть у вас и у 12 компаний группы.', [LOA, 'feat:group_loans', KR1], 'high'),
    ai('Одновременно слабеет рубль, а 43 % ваших платежей идут импортёрам группы — давление на оборотный капитал с двух сторон.', ['feat:intra_group_suppliers', KR2]),
    ai('Спрос автобизнеса группы под вопросом: лимиты по автокредитам ужесточены с 1 октября.', [GROUP, CON1]),
  ],
  'p-u8318-acc': [
    ai('Слабеющий рубль даст курсовые разницы по закупкам у импортёров группы — нужен аккуратный валютный контроль.', ['feat:intra_group_suppliers', KR2]),
    ai('ФОТ растёт быстрее плана: зарплаты в экономике +9,6 %, у компании больше 251 сотрудника.', [WORKERS, M7_2], 'high'),
    ai('Процентные расходы по кредиту останутся высокими в отчётности 4К26.', [LOA, KR1]),
  ],
  'p-u57706-owner': [
    ai('Бюджет — главный фактор для группы: госзаказ держит дорожное и жилищное строительство, но он же держит ставку высокой.', [GROUP, FI9]),
    ai('Ядро холдинга — топливо: переработка сокращается, цены растут.', [OKVED, H2]),
    ai('Ставка 14 % работает в обе стороны: доход по вашему депозиту и дорогие деньги для стройки группы.', [DEP, GROUP, KR1], 'high'),
  ],
  'p-u57706-tre': [
    ai('Доходность размещения останется высокой до конца года: банк ждёт ставку 14 %.', [DEP, KR1], 'high'),
    ai('Для ликвидности банк советует защитный портфель — флоатеры, короткие ОФЗ, корпоративный фикс до 3 лет.', [FI3, FI24]),
  ],
  'p-u34911-ceo': [
    ai('Сложности с вывозом урожая давят на внутренние цены зерна — это ваша отрасль.', [OKVED, INF1]),
    ai('Слабый рубль увеличивает рублёвую выручку экспорта; направление ВЭД — оценка по отрасли и странам.', [FTS, 'feat:fts_direction', KR2]),
    ai('Правила вывоза и загрузка портов — главный операционный риск; позиции банка по теме нет.', [FTS, 'src:news:grain-export'], 'low'),
  ],
  'p-u34911-tre': [
    ai('Валютная выручка (экспорт — оценка) растёт в рублях: банк ждёт 87,2 ₽/$ к концу года и 93 ₽/$ к концу 2027-го.', [FTS, KR2]),
    ai('Оборотный кредит не подешевеет до конца года.', [LOA, KR1], 'high'),
  ],
  'p-u258116-ceo': [
    ai('53 % поступлений в видимом банку обороте — от ресторанов и кафе, а потребление услуг замедляется: банк ждёт около нуля в 4К26.', ['feat:demand_56', CON1], 'high'),
    ai('Одновременно дорожает импорт из Китая и Индонезии — маржу сжимает с двух сторон.', [FTS, KR2]),
    ai('Зарплаты растут и у вас, и у ресторанов-покупателей.', [WORKERS, M7_2]),
  ],
};

// ─── Подробные разборы (по эталонам) ─────────────────────────────────────────

export interface MockDetail {
  breakdown: ScoreTerm[];
  why: Statement[];
  risks: Statement[];
  opportunities: Statement[];
  factors: Statement[];
  actions: Insight['actions'];
  warnings: string[];
  exposure: Exposure;
  group_impact?: GroupImpact;
  bank_vs_market?: BankVsMarket;
  estimates?: Estimate[];
}

const RATE_DIVERGES: BankVsMarket = {
  verdict: 'diverges',
  summary: 'Банк жёстче рынка: ждёт среднюю ставку 2027 года 13,0 % против консенсуса 12,4 %',
  bank: bank('Средняя ключевая ставка в 2027 году — 13,0 %', [KR2]),
  market: fact('Консенсус аналитиков по средней ставке 2027 года — 12,4 %; диапазон ЦБ — 10,5–12,5 %', [KR3]),
};

const RATE_ESTIMATE: Estimate = {
  id: 'rate',
  title: 'Процентные расходы по плавающему долгу',
  formula: 'долг × изменение ставки',
  input: { label: 'Ваш долг по плавающей ставке', unit: 'млн ₽', hint: 'Суммы и типа ставки кредита в данных банка нет — введите сами' },
  result_label: 'Дополнительные проценты в год',
  scenarios: [
    { id: 'base', label: 'Базовый: 14,0 % — прогноз банка', multiplier: 0.005, basis: bank('Банк ждёт 14,0 % до конца 2026 года вместо прежних 13,5 % — разница 0,5 п.п.', [KR1, H3]) },
    { id: 'hard', label: 'Жёсткий: 15,0 %', multiplier: 0.015, basis: est('Допущение сервиса: ставка 15,0 %, на 1,5 п.п. выше прежнего ориентира банка 13,5 %') },
    { id: 'soft', label: 'Мягкий: 13,5 %', multiplier: 0, basis: est('Допущение сервиса: ставка возвращается к прежнему ориентиру банка 13,5 %') },
  ],
  assumptions: ['Расчёт на год; весь введённый долг — по плавающей ставке', 'Сравнение с прежним прогнозом банка 13,5 % на конец 2026 года'],
};

const A_EXPOSURE: Exposure = {
  channels: [
    { kind: 'direct', factor: F.rate, text: 'Ваш кредит в Альфа-Банке', counterparties: [] },
    {
      kind: 'suppliers',
      factor: F.fx,
      text: 'Импортёры внутри группы — 43 % всех платежей',
      sector: 'импорт автозапчастей',
      share: 0.435,
      counterparties: [
        { id: 'U_92457', label: 'импортёр запчастей, ВЭД ОАЭ, Индия, Китай', share: 0.384, amount_bn: 7.25, intra_group: true },
        { id: 'U_52177', label: 'импортёр запчастей, ВЭД Китай, Турция, Камбоджа', share: 0.051, amount_bn: 0.97, intra_group: true },
      ],
    },
    {
      kind: 'suppliers',
      factor: F.supply45,
      text: 'Внешние поставщики: оптовики запчастей — 50,9 % внешних платежей, опт — 14,0 %',
      sector: 'торговля автозапчастями',
      share: null,
      coverage: 0.71,
      counterparties: [],
    },
    { kind: 'group', factor: F.rate, text: 'Кредит у 12 из 29 компаний группы', counterparties: [] },
  ],
  gaps: [
    'Отраслевой позиции банка по поставщикам запчастей нет — канал показан, но вывод не усиливает',
    'О 76 % поступлений отрасль покупателя неизвестна; 46 % — один плательщик вне данных банка',
  ],
};

const B_GROUP: GroupImpact = {
  group_id: 'group_134402_sb',
  companies_total: 369,
  affected_revenue_bn: 117.2,
  affected: [
    { id: 'U_4909', label: 'ТЭС', revenue_bn: 31.0, factors: [F.rate] },
    { id: 'U_191099', label: 'дорожный строитель', revenue_bn: 28.8, factors: [F.rate, F.gov] },
    { id: 'U_201985', label: 'жилищный строитель, ВЭД Турция', revenue_bn: 25.0, factors: [F.rate, F.gov] },
    { id: 'U_122823', label: 'строитель с гарантиями', revenue_bn: 13.5, factors: [F.rate, F.gov] },
    { id: 'U_178740', label: 'заказчик-застройщик', revenue_bn: 11.0, factors: [F.rate] },
    { id: 'U_417124', label: 'дорожный строитель', revenue_bn: 7.9, factors: [F.rate, F.gov] },
  ],
};

/** details[`${eventId}|${personaId}`] */
export const details: Record<string, MockDetail> = {
  'ev-keyrate|p-u8318-cfo': {
    breakdown: [
      { label: 'Ставка × ваш кредит', value: 0.38 },
      { label: 'Вес роли: финдиректору важны долг и ставка', value: 0.22 },
      { label: 'Ставка × кредиты 12 компаний группы', value: 0.14 },
      { label: 'Валюта закупок группы', value: 0.09 },
      { label: 'Есть позиция банка', value: 0.05 },
      { label: 'Свежесть', value: 0.03 },
    ],
    why: [
      data('У компании кредит в Альфа-Банке, кредиты есть ещё у 12 из 29 компаний группы — от автосервисов до автосалонов', [LOA, 'feat:group_loans']),
      data('43 % ваших платежей (8,2 из 18,9 млрд ₽ в видимом банку обороте) идут двум компаниям группы, которые ведут ВЭД с Китаем, ОАЭ, Индией, Турцией', ['feat:intra_group_suppliers', 'feat:group_fts_countries']),
      ai('Дешевле обслуживать долг до конца года не станет, а закупки у импортёров группы дорожают вместе с ослаблением рубля — давление на оборотный капитал с двух сторон', [LOA, 'feat:intra_group_suppliers', KR2], 'high'),
    ],
    risks: [
      ai('Процентные расходы по оборотным кредитам останутся на текущем уровне до 2027 года; если часть долга плавающая, «ждать снижения» в бюджете на 4К26 нельзя. Тип ставки в данных банка не указан', [LOA, KR1], 'high'),
      ai('Слабеющий рубль удорожает импорт группы; переложить рост в цены сложнее, когда авторынок замедляется', ['feat:intra_group_suppliers', KR2, CON1]),
      ai('Автосалоны группы первыми почувствуют дорогие автокредиты и лимиты по ним с 1 октября', [GROUP, CON1]),
    ],
    opportunities: [
      {
        ...ai('Падение продаж новых автомобилей удлиняет срок жизни парка — спрос на запчасти может держаться лучше, чем на машины. Данными компании не подтверждено', [OKVED, M7_1], 'low'),
        check: {
          confirm: 'рост поступлений от автосервисов и оптовиков запчастей в следующих выгрузках платежей',
          refute: 'их падение',
        },
      },
    ],
    factors: [ai('Решения ЦБ 23 октября и 18 декабря; курс юаня — закупки из Китая; продажи авто и автокредиты', [KR1, KR2, CON1])],
    actions: [
      { text: 'Какая доля долга группы — по плавающей ставке и когда ближайшие погашения?', kind: 'question', refs: [LOA, 'feat:group_loans'] },
      { text: 'Бюджет на 4К26–1К27 при ставке 14 % (банк) и 15 % (жёсткий вариант, допущение сервиса)', kind: 'scenario', refs: [KR1] },
      { text: 'В какой валюте и на каких условиях импортёры группы платят поставщикам — есть ли окно для фиксации курса?', kind: 'question', refs: ['feat:intra_group_suppliers'] },
      { text: 'Кредит у вас уже есть — проверьте условия: фиксированная ставка или рефинансирование части долга', kind: 'product', product: 'refinancing', refs: [LOA] },
    ],
    warnings: [
      'Тип ставки и сумма долга в данных банка неизвестны',
      'Направление ВЭД компаний группы — оценка по отрасли',
      'О 76 % поступлений отрасль покупателя неизвестна',
    ],
    exposure: A_EXPOSURE,
    bank_vs_market: RATE_DIVERGES,
    estimates: [RATE_ESTIMATE],
  },
  'ev-keyrate|p-u8318-acc': {
    breakdown: [
      { label: 'Ставка × ваш кредит', value: 0.38 },
      { label: 'Вес роли: главбуху важнее учёт и налоги, чем стоимость долга', value: 0.12 },
      { label: 'Кредиты компаний группы', value: 0.1 },
      { label: 'Валюта закупок группы', value: 0.05 },
      { label: 'Есть позиция банка', value: 0.05 },
      { label: 'Свежесть', value: 0.03 },
    ],
    why: [
      data('У компании кредит в банке, кредиты есть ещё у 12 из 29 компаний группы', [LOA, 'feat:group_loans']),
      ai('Процентные расходы по кредиту компании и группы останутся высокими до конца года — это прямо видно в отчётности 4К26', [LOA, KR1], 'high'),
      ai('Закупки у импортёров группы при слабеющем рубле дают курсовые разницы и требуют аккуратного валютного контроля по внешнеторговым контрактам компаний группы', ['feat:intra_group_suppliers', KR2], 'high'),
      data('Больше 251 сотрудника и зарплатный проект: при росте зарплат в экономике на 9,6 % ФОТ и взносы растут быстрее плана, если план исходил из охлаждения рынка труда', [WORKERS, ZPP, M7_2]),
    ],
    risks: [ai('Курсовые разницы в 4К26 по закупкам у импортёров группы', ['feat:intra_group_suppliers', KR2])],
    opportunities: [],
    factors: [ai('Решения ЦБ 23 октября и 18 декабря; курс юаня', [KR1, KR2])],
    actions: [
      { text: 'Как внутригрупповые закупки (8,2 млрд ₽) отражены в ценах сделок между компаниями группы?', kind: 'question', refs: ['feat:intra_group_suppliers'] },
      { text: 'Запланировать резерв на курсовые разницы в 4К26', kind: 'scenario', refs: [KR2] },
    ],
    warnings: ['Тип ставки и сумма долга в данных банка неизвестны', 'Направление ВЭД компаний группы — оценка по отрасли'],
    exposure: A_EXPOSURE,
    bank_vs_market: RATE_DIVERGES,
  },
  'ev-keyrate|p-u57706-owner': {
    breakdown: [
      { label: 'Ставка × строительный контур группы', value: 0.3 },
      { label: 'Ставка × ваш депозит (доход)', value: 0.18 },
      { label: 'Вес роли: собственнику важны группа и стратегия', value: 0.17 },
      { label: 'Есть позиция банка', value: 0.05 },
      { label: 'Свежесть', value: 0.03 },
    ],
    why: [
      data('Ваша компания держит депозит в банке и не имеет кредита: высокая ставка «дольше» — это доход на свободных деньгах', [DEP, LOA]),
      data('В группе 369 компаний и 302,7 млрд ₽ выручки; крупнейшие после вас — генерация, два дорожных строителя, жилищное строительство, заказчик-застройщик. У 41 компании группы лизинг, у 7 — гарантии', [GROUP, 'feat:group_products']),
      ai('Для группы событие двустороннее: ядро с депозитами выигрывает, строительный контур платит дороже за деньги дольше, чем ждали летом', [DEP, GROUP, KR1], 'high'),
    ],
    risks: [
      ai('Строительные компании группы: дорогой долг и инвестиции в экономике −4 % — давление на маржу и сроки проектов. Гарантии у вас и у 7 компаний группы указывают на госзаказ — опора на бюджет', [GROUP, GAR, H3]),
      ai('Если новый трёхлетний бюджет расширит расходы, ставка останется высокой дольше: для дорожного строительства группы это больше контрактов и дороже деньги', [GROUP, FI9]),
    ],
    opportunities: [ai('Доходность размещения свободных средств останется около текущей до конца 2026 года', [DEP, KR1], 'high')],
    factors: [ai('Решение 23 октября; параметры трёхлетнего бюджета; цены на топливо — ядро бизнеса', [KR1, FI9, H2])],
    actions: [
      { text: 'Распределить свободные средства группы между депозитом и короткими инструментами на горизонт до 2027 года', kind: 'scenario', refs: [DEP, FI3] },
      { text: 'Как строительные компании группы финансируют проекты — плавающая ставка, лизинг, авансы по госконтрактам?', kind: 'question', refs: [GROUP] },
      { text: 'Можно ли кредитовать стройку группы внутригрупповыми займами вместо банковского долга?', kind: 'question', refs: [GROUP, DEP] },
      { text: 'Депозит у вас уже есть — проверьте срок и условия размещения до конца года', kind: 'product', product: 'deposit', refs: [DEP] },
    ],
    warnings: ['Платежи компании покрывают меньше 1 % выручки — цепочек через контрагентов нет', 'Остатки на счетах неизвестны'],
    exposure: {
      channels: [
        { kind: 'direct', factor: F.deposit, text: 'Ваш депозит в банке — ставка работает как доход', counterparties: [] },
        {
          kind: 'group',
          factor: F.rate,
          text: 'Строительный контур группы: дороги, жильё, генерация — 6 крупных компаний, список ниже',
          counterparties: [],
        },
      ],
      gaps: ['Платежи компании покрывают меньше 1 % выручки — цепочек через покупателей и поставщиков нет'],
    },
    group_impact: B_GROUP,
    bank_vs_market: RATE_DIVERGES,
    estimates: [
      {
        id: 'deposit',
        title: 'Доход на свободные средства',
        formula: 'сумма × ставка размещения',
        input: { label: 'Свободные средства', unit: 'млн ₽', hint: 'Остатков на счетах в данных нет — введите сами' },
        result_label: 'Доход в год',
        scenarios: [
          { id: 'base', label: 'Базовый: 14 % до конца 2026 года', multiplier: 0.14, basis: bank('Банк ждёт ключевую ставку 14,0 % до конца 2026 года', [KR1]) },
          { id: 'soft', label: 'Снижение: 12 % — прогноз банка на конец 2027 года', multiplier: 0.12, basis: bank('На конец 2027 года банк ждёт 12,0 %', [KR2]) },
          { id: 'hard', label: 'Выше: 15 %', multiplier: 0.15, basis: est('Допущение сервиса: ставка 15 %') },
        ],
        assumptions: ['Ставка размещения следует за ключевой — допущение сервиса', 'Ставок депозитов в материалах банка нет'],
      },
    ],
  },
  'ev-consumption|p-u258116-ceo': {
    breakdown: [
      { label: 'Потребление × покупатели-рестораны (53 % поступлений)', value: 0.48 },
      { label: 'Вес роли: гендиректору важен спрос', value: 0.2 },
      { label: 'Валюта импорта', value: 0.1 },
      { label: 'Свежесть', value: 0.08 },
      { label: 'Есть позиция банка', value: 0.05 },
    ],
    why: [
      data('53 % поступлений компании (1,1 из 2,1 млрд ₽ в видимом банку обороте) — от ресторанов и кафе; крупнейший покупатель даёт лишь 2 %, это спрос всего сегмента. Покрытие отраслей — 66 %', ['feat:demand_56', 'feat:payers_coverage']),
      data('Компания импортирует из Китая, Индонезии и Узбекистана; 17,5 % платежей — логистике', [FTS, 'feat:supply_52']),
      ai('Замедление услуг бьёт по вашей выручке через закупки ресторанов, а слабый рубль одновременно поднимает себестоимость импорта — маржу сжимает с двух сторон', ['feat:demand_56', FTS, KR2], 'high'),
    ],
    risks: [
      ai('Рестораны первыми сокращают закупки и растягивают оплату при падении трафика — рост дебиторки при 1 058 мелких плательщиках', ['feat:demand_56'], 'high'),
      ai('Рестораны платят персоналу больше — их маржа сжимается, давление на ваши цены', ['feat:demand_56', M7_2]),
      ai('Импорт из Китая дорожает с курсом: 13,0 → 13,8 ₽/¥ по прогнозу банка', [FTS, KR2]),
    ],
    opportunities: [
      {
        ...ai('Спрос перетекает из услуг в товары — розничный канал группы может компенсировать часть просадки', [GROUP, H2], 'low'),
        check: { confirm: 'рост доли поступлений от розницы (47) против общепита (56)' },
      },
    ],
    factors: [ai('Трафик и средний чек общепита; курс юаня; стоимость логистики из Азии', ['feat:demand_56', KR2, 'feat:supply_52'])],
    actions: [
      { text: 'Какая доля дебиторки — у ресторанов, как менялись сроки оплаты с лета?', kind: 'question', refs: ['feat:demand_56'] },
      { text: 'Выручка от общепита при нулевом росте потребления в 4К26 и при снижении на 5 % (допущение сервиса)', kind: 'scenario', refs: ['feat:demand_56', CON1] },
      { text: 'Можно ли нарастить продажи в розницу и пищепром, чтобы снизить зависимость от общепита?', kind: 'question', refs: ['feat:demand_56'] },
      { text: 'Факторинг: финансирование поставок ресторанам без ожидания оплаты и защита от их неплатежей — у компании его нет', kind: 'product', product: 'factoring', refs: [FACTORING, 'feat:demand_56'] },
    ],
    warnings: ['34 % поступлений — от плательщиков вне данных банка', '«Импорт» — оценка по отрасли: направление ВЭД в данных не указано', 'Позиции банка именно по общепиту нет — связь «услуги → рестораны → вы» делает модель'],
    exposure: {
      channels: [
        {
          kind: 'buyers',
          factor: F.demand56,
          text: 'Рестораны и кафе — 53 % поступлений, 1 058 плательщиков, крупнейший даёт 2 %',
          sector: 'общепит (ОКВЭД 56)',
          share: 0.531,
          coverage: 0.66,
          counterparties: [],
        },
        {
          kind: 'suppliers',
          factor: F.supply52,
          text: 'Логистика — 17,5 % платежей; крупнейший получатель — в Приморском крае',
          sector: 'склады и логистика (ОКВЭД 52)',
          share: 0.175,
          coverage: 0.74,
          counterparties: [{ id: 'U_201066', label: 'логистика, Приморский край', share: 0.169 }],
        },
        { kind: 'direct', factor: F.fx, text: 'Импорт из Китая, Индонезии, Узбекистана — оценка по отрасли', counterparties: [] },
      ],
      gaps: ['34 % поступлений — от плательщиков вне данных банка'],
    },
    bank_vs_market: {
      verdict: 'agrees',
      summary: 'Данные совпадают с ожиданием банка: потребление на пике. Ожиданий рынка в материалах нет',
      bank: bank('Потребление на пике, в 4К26 — около нуля г/г; банк ждал розницу в августе +3,5 %', [CON1, M7_3]),
    },
  },
  'ev-harvest|p-u34911-ceo': {
    breakdown: [
      { label: 'Сырьё: своя отрасль — зерно', value: 0.45 },
      { label: 'Валюта: экспорт (оценка)', value: 0.18 },
      { label: 'Вес роли: гендиректору важны рынки сбыта', value: 0.15 },
      { label: 'Свежесть', value: 0.08 },
      { label: 'Есть позиция банка', value: 0.05 },
    ],
    why: [
      data('Компания — крупнейший в данных банка оптовик зерна (№ 1 из 204), ведёт ВЭД с ОАЭ, Алжиром и Индией, кредит в банке', [OKVED, 'feat:position', FTS, LOA]),
      ai('Направление ВЭД в данных не указано; по отрасли и странам вероятен экспорт — внутренних поступлений в данных почти нет, что с этим согласуется', ['feat:fts_direction', 'feat:payments_gap']),
    ],
    risks: [
      ai('Трудности с вывозом урожая давят на внутренние цены зерна — хуже условия на внутреннем рынке и выше запасы', [OKVED, INF1]),
      ai('Топливо дорожает — дороже доставка до портов', [INF1, H2]),
    ],
    opportunities: [ai('Слабеющий рубль увеличивает рублёвую выручку экспортного контракта', [FTS, KR2])],
    factors: [ai('Правила вывоза и загрузка портов; курс доллара', ['src:news:grain-export', KR2], 'low')],
    actions: [
      { text: 'Какая доля выручки — валютная и когда она поступает?', kind: 'question', refs: [FTS] },
      { text: 'Сценарий продаж «экспорт или внутренний рынок» при курсе по прогнозу банка', kind: 'scenario', refs: [KR2] },
      { text: 'Как устроена логистика до портов и сколько стоит простой?', kind: 'question', refs: [OKVED] },
      { text: 'Валютный контроль и инструменты хеджирования; кредит уже есть — проверьте условия', kind: 'product', product: 'fx_hedge', refs: [FTS, LOA] },
    ],
    warnings: ['Направление ВЭД — оценка по отрасли', 'О 88 % платежей поставщикам отрасль неизвестна'],
    exposure: {
      channels: [
        { kind: 'direct', factor: F.agro, text: 'Своя отрасль — оптовая торговля зерном', counterparties: [] },
        { kind: 'direct', factor: F.fx, text: 'ВЭД с ОАЭ, Алжиром, Индией; экспорт — оценка по отрасли', counterparties: [] },
      ],
      gaps: ['Внутренних поступлений в данных почти нет — 0,01 млрд ₽', 'Отрасль известна лишь у 12 % платежей поставщикам — цепочек через контрагентов не строим'],
    },
    bank_vs_market: {
      verdict: 'agrees',
      summary: 'Банк сам читает дефляцию как сигнал дезинфляции и ждал по августу −0,07 % м/м',
      bank: bank('Недельная дефляция — сигнал дезинфляции; за август банк оценивал цены в −0,07 % м/м', [INF1]),
    },
    estimates: [
      {
        id: 'fx',
        title: 'Рублёвая выручка от экспорта',
        formula: 'валютная выручка × изменение курса',
        input: {
          label: 'Валютная выручка в год в рублях по курсу 87,2 ₽/$',
          unit: 'млн ₽',
          hint: 'Объёма ВЭД в данных нет — введите сами. Курс 87,2 ₽/$ — прогноз банка на конец 2026 года',
        },
        result_label: 'Изменение рублёвой выручки за год',
        scenarios: [
          { id: 'base', label: 'Прогноз банка: 87,2 → 93,0 ₽/$', multiplier: 0.0665, basis: bank('Рубль 87,2 ₽/$ на конец 2026 года и 93,0 ₽/$ на конец 2027 года: ослабление на 6,65 % за 2027 год', [KR2]) },
          { id: 'hard', label: 'Рубль слабее на 10 %', multiplier: 0.1, basis: est('Допущение сервиса: ослабление рубля на 10 % — на каждые 100 млн ₽ выручки +10 млн ₽') },
          { id: 'soft', label: 'Курс не меняется', multiplier: 0, basis: est('Допущение сервиса: курс остаётся 87,2 ₽/$') },
        ],
        assumptions: [
          'Вся валютная выручка — в долларах: валюта и направление ВЭД в данных не указаны',
          'Сумму вводите по курсу 87,2 ₽/$ — от него считается изменение',
          'Без учёта пошлин и логистики',
        ],
      },
    ],
  },
};

// ─── Карты чувствительности (по ожидаемым картам демо-клиентов) ──────────────

const FX_BANK = bank('Рубль: 87,2 ₽/$ и 13,0 ₽/¥ на конец 2026 года, 93,0 ₽/$ и 13,8 ₽/¥ на конец 2027 года', [KR2]);
const RATE_BANK = bank('Ставка 14,0 % до конца 2026 года и 12,0 % к концу 2027 года', [KR1, KR2]);
const VED_BANK = bank('Выгода от экспорта может не реализоваться из-за логистики и санкционных рисков', [H3]);
const INFL_BANK = bank('Топливо и ослабление рубля — главные проинфляционные риски', [INF1]);
const LABOR_FACT = fact('Номинальные зарплаты в июне выросли на 9,6 % г/г', [M7_2]);
const LABOR_BANK = bank('Рынок труда не охлаждается — главный аргумент против быстрого снижения ставки', [M7_1]);

const sf = (
  factor: FactorRef,
  strength: Strength,
  channel_text: string,
  evidence: Statement[],
  coverage: number | null = null,
): SensitivityFactor => ({ factor, strength, channel_text, evidence, coverage, recent_event_ids: [] });

export const exposureMaps: Record<string, ExposureMap> = {
  U_8318: {
    company_id: 'U_8318',
    position: { okved: '45.31.1', rank: 1, total: 422 },
    factors: [
      sf(F.fx, 'high', 'через поставщиков-импортёров своей группы: 43 % всех платежей', [
        data('43 % платежей (8,2 из 18,9 млрд ₽) — двум компаниям группы с ВЭД: Китай, ОАЭ, Индия, Турция', ['feat:intra_group_suppliers', 'feat:group_fts_countries']),
        ai('Направление «импорт» — оценка по отрасли: в данных ВЭД нет направления', ['feat:group_fts_countries']),
        FX_BANK,
      ]),
      sf(F.rate, 'high', 'собственный кредит и кредиты у 12 компаний группы', [
        data('Кредит в банке есть у компании и ещё у 12 из 29 компаний группы', [LOA, 'feat:group_loans']),
        RATE_BANK,
      ]),
      sf(F.consumer, 'high', 'своя отрасль — авторынок; в группе автосалоны и автосервисы', [
        data('Основная деятельность — опт автозапчастями; в группе автосалоны и автосервисы', [OKVED, GROUP]),
        bank('Продажи автомобилей уходят в минус, лимиты по автокредитам ужесточены с 1 октября', [CON1]),
      ]),
      sf(F.ved, 'medium', 'через импортёров группы: Китай, ОАЭ, Индия, Турция, Камбоджа', [
        data('ВЭД ведут две компании группы', ['feat:group_fts_countries']),
        VED_BANK,
      ]),
      sf(F.supply45, 'medium', 'половина внешних закупок — у других оптовиков запчастей', [
        data('Оптовики запчастей — 50,9 % внешних платежей поставщикам', ['feat:supply_45']),
      ], 0.71),
      sf(F.demand45, 'low', 'известные покупатели — оптовики запчастей, 21,6 % поступлений', [
        data('Отрасль известна лишь у 24 % поступлений; 46 % — один плательщик вне данных банка', ['feat:payers_coverage']),
      ], 0.24),
      sf(F.labor, 'medium', 'больше 251 сотрудника, зарплатный проект', [
        data('Больше 251 сотрудника по данным ФНС, зарплатный проект в банке', [WORKERS, ZPP]),
        LABOR_FACT,
        LABOR_BANK,
      ]),
      sf(F.inflation, 'medium', 'торговля импортными товарами с длинной цепочкой поставок', [
        ai('Импортные запчасти дорожают вместе с курсом и логистикой', [OKVED], 'medium'),
        INFL_BANK,
      ]),
      sf(F.gov, 'none', 'отрасль не бюджетная, гарантий банка нет', [data('Гарантий банка нет, отрасль — торговля', [GAR, OKVED])]),
      sf(F.deposit, 'none', 'депозитов в банке нет', [data('Депозитов в банке нет', [DEP])]),
    ],
  },
  U_57706: {
    company_id: 'U_57706',
    position: { okved: '46.71', rank: 1, total: 661 },
    factors: [
      sf(F.oil, 'high', 'своя отрасль — оптовая торговля топливом', [
        data('Основная деятельность — оптовая торговля топливом', [OKVED]),
        fact('Бензин подорожал на 26 % за 12 месяцев на 27 июля', [H2]),
        bank('Топливный кризис — сокращение переработки и рост цен — один из главных проинфляционных рисков', [FI13]),
      ]),
      sf(F.deposit, 'high', 'свои депозиты: высокая ставка дольше — это доход', [
        data('Депозит в банке есть, кредита нет', [DEP, LOA]),
        bank('Ставка 14,0 % до конца 2026 года; для ликвидности — защитный портфель 12–16 % годовых', [KR1, FI3, FI24]),
      ]),
      sf(F.gov, 'high', 'через группу: два дорожных строителя, жильё и застройщики; свои гарантии', [
        data('В группе дорожные и жилищные строители, у компании — гарантии банка', [GROUP, GAR]),
        bank('Бюджет — главный риск для снижения ставки; госпроекты — главный источник роста промышленности', [FI9, KR1, H3]),
      ]),
      sf(F.rate, 'medium', 'у самой компании только лизинг; капиталоёмкие компании группы', [
        data('Лизинг у компании и у 41 компании группы, кредит — у 3', [LEA, 'feat:group_products']),
        RATE_BANK,
      ]),
      sf(F.fx, 'medium', 'ВЭД с Казахстаном и Киргизией; направление — оценка по отрасли', [
        data('ВЭД: Киргизия, Казахстан', [FTS]),
        ai('Вероятно, поставки топлива в ЕАЭС — оценка по отрасли', [OKVED, FTS], 'low'),
        FX_BANK,
      ]),
      sf(F.ved, 'low', 'страны ЕАЭС', [data('ВЭД: Киргизия, Казахстан', [FTS])]),
      sf(F.labor, 'low', '16–100 сотрудников', [data('16–100 сотрудников по данным ФНС', [WORKERS])]),
      sf(F.demand, 'no_data', 'платежи компании в данных — меньше 1 % выручки', [
        data('Платежи компании покрывают меньше 1 % выручки — цепочек через покупателей не строим', ['feat:payments_coverage']),
      ], 0.11),
      sf(F.supply, 'no_data', 'платежи компании в данных — меньше 1 % выручки', [
        data('Платежи компании покрывают меньше 1 % выручки — цепочек через поставщиков не строим', ['feat:payments_coverage']),
      ], 0),
    ],
  },
  U_34911: {
    company_id: 'U_34911',
    position: { okved: '46.21', rank: 1, total: 204 },
    factors: [
      sf(F.fx, 'high', 'ВЭД с ОАЭ, Алжиром, Индией; «экспорт» — оценка по отрасли', [
        data('ВЭД: ОАЭ, Алжир, Индия', [FTS]),
        ai('По отрасли и странам вероятен экспорт; внутренних поступлений почти нет', ['feat:fts_direction', 'feat:payments_gap']),
        FX_BANK,
      ]),
      sf(F.agro, 'high', 'своя отрасль — зерно', [
        data('Основная деятельность — опт зерном', [OKVED]),
        bank('Продовольствие может пойти ниже из-за сложностей с экспортом урожая', [INF1]),
      ]),
      sf(F.ved, 'high', 'экспорт в Северную Африку, Ближний Восток, Индию', [data('ВЭД: ОАЭ, Алжир, Индия', [FTS]), VED_BANK]),
      sf(F.rate, 'high', 'собственный кредит; торговля зерном — оборотный капитал', [
        data('Кредит в банке', [LOA]),
        ai('Торговля зерном держится на оборотном кредите', [OKVED], 'medium'),
        RATE_BANK,
      ]),
      sf(F.inflation, 'medium', 'цены на продовольствие внутри страны', [
        data('Основная деятельность — опт зерном: цены продажи внутри страны', [OKVED]),
        INFL_BANK,
      ]),
      sf(F.oil, 'medium', 'логистика зерна — грузовые перевозки', [
        ai('Доставка зерна до портов дорожает вместе с топливом', [OKVED], 'medium'),
        INFL_BANK,
      ]),
      sf(F.region, 'medium', 'юг России, порты Азово-Черноморского бассейна', [
        data('Регион — Ростовская область', ['feat:REGION']),
        ai('Экспорт идёт через порты юга', ['feat:REGION'], 'low'),
      ]),
      sf(F.demand, 'no_data', 'внутренних поступлений в данных почти нет', [
        data('Внутренних поступлений 0,01 млрд ₽', ['feat:payments_gap']),
      ]),
      sf(F.supply, 'low', 'поставщики известны лишь частично', [
        data('Отрасль известна у 12 % платежей поставщикам', ['feat:payments_gap']),
      ], 0.12),
      sf(F.labor, 'low', '16–100 сотрудников', [data('16–100 сотрудников по данным ФНС', [WORKERS])]),
      sf(F.gov, 'none', 'гарантий нет, отрасль не бюджетная', [data('Гарантий банка нет', [GAR])]),
      sf(F.deposit, 'none', 'депозитов в банке нет', [data('Депозитов в банке нет', [DEP])]),
    ],
  },
  U_258116: {
    company_id: 'U_258116',
    position: { okved: '46.90', rank: 8, total: 3151 },
    factors: [
      sf(F.demand56, 'high', 'через покупателей: рестораны и кафе — 53 % поступлений, 1 058 плательщиков', [
        data('Рестораны и кафе — 53 % поступлений в видимом банку обороте', ['feat:demand_56', 'feat:payers_coverage']),
        fact('Потребление услуг в июне выросло лишь на 1,7 % г/г', [H2]),
        bank('Потребление на пике: в 4К26 — около нуля г/г', [CON1]),
      ], 0.66),
      sf(F.consumer, 'high', 'через покупателей из общепита', [
        data('Рестораны и кафе — 53 % поступлений', ['feat:demand_56']),
        bank('Потребление в 4К26 — около нуля г/г', [CON1]),
      ]),
      sf(F.fx, 'high', 'ВЭД с Китаем, Индонезией, Узбекистаном; «импорт» — оценка по отрасли', [
        data('ВЭД: Китай, Индонезия, Узбекистан', [FTS]),
        FX_BANK,
      ]),
      sf(F.labor, 'medium', 'больше 251 сотрудника; у покупателей-ресторанов зарплаты растут', [
        data('Больше 251 сотрудника, зарплатный проект', [WORKERS, ZPP]),
        LABOR_FACT,
        LABOR_BANK,
      ]),
      sf(F.supply52, 'medium', 'логистика — 17,5 % платежей', [
        data('Логистика — 17,5 % платежей поставщикам', ['feat:supply_52']),
        INFL_BANK,
      ], 0.74),
      sf(F.rate, 'medium', 'лизинг', [data('Лизинг в банке', [LEA]), RATE_BANK]),
      sf(F.ved, 'medium', 'Китай, Индонезия, Узбекистан', [data('ВЭД: Китай, Индонезия, Узбекистан', [FTS]), VED_BANK]),
      sf(F.inflation, 'medium', 'импортные товары и перенос издержек покупателями', [
        ai('Покупатели переносят свои издержки в цены закупки', ['feat:demand_56'], 'low'),
        INFL_BANK,
      ]),
      sf(F.gov, 'none', 'отрасль не бюджетная', [data('Гарантий банка нет', [GAR])]),
      sf(F.deposit, 'none', 'депозитов в банке нет', [data('Депозитов в банке нет', [DEP])]),
    ],
  },
};
