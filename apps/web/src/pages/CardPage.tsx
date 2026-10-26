import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { AgentStep, CompanyProfile, EventDetail, FeedItem, Insight } from '../api/types';
import { AskBox } from '../components/AskBox';
import { Disclaimer } from '../components/Disclaimer';
import { FeedbackBox } from '../components/FeedbackBox';
import { FullText } from '../components/FullText';
import { Icon, type IconName } from '../components/Icon';
import { MoreMenu } from '../components/MoreMenu';
import { ExpandButton, LevelIcon, NewsThumb } from '../components/NewsParts';
import { RequestForm, type RequestKind } from '../components/RequestForm';
import { SourceView, StatementList, type RefIndex } from '../components/Statement';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { Thinking } from '../components/Thinking';
import { useBriefing } from '../state/briefing';
import { useHidden } from '../state/hidden';
import { roleLabel } from '../state/labels';
import { bankOf, LEVEL_LABEL, levelWith, plain, whyOf } from '../state/news';
import { tracePath } from '../state/routes';
import { cardScreen, isHypothesis, type CardMenuItem, type CardRow } from '../state/screens';
import { useCurrentUser } from '../state/session';
import { markRead } from '../state/read';
import { progressOf, stepsOf } from '../state/steps';
import { useAsync, type AsyncState } from '../state/useAsync';
import { useInsight } from '../state/useInsight';
import { capitalize, claimsOf, managerLabel } from '../state/trust';
import { ClaimsCheck } from '../components/TrustParts';
import { RelatedNews } from '../components/RelatedNews';
import { topicOf } from '../state/topic';

const ROW_ICON: Record<CardRow['id'], IconName> = {
  chain: 'group',
  risks: 'warning',
  hypotheses: 'hypothesis',
  estimates: 'calc',
  sources: 'fact',
  trace: 'model',
  ask: 'chat',
};

/** Раскрываемый блок подробностей: своя иконка, шеврон вниз ↔ вверх, содержимое плавно появляется. */
function Row({ row, children }: { row: CardRow; children: ReactNode }) {
  return (
    <details className="xrow">
      <summary>
        <span className="xrow__icon">
          <Icon name={ROW_ICON[row.id]} size={18} />
        </span>
        <span className="xrow__text">
          <span className="xrow__title">{row.title}</span>
          <span className="xrow__summary">{row.summary}</span>
        </span>
        <Icon name="chevronDown" size={18} className="xrow__chevron" />
      </summary>
      <div className="xrow__body">{children}</div>
    </details>
  );
}

function BackToNews() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <button type="button" className="back back--pill" onClick={() => (location.key !== 'default' ? navigate(-1) : navigate('/radar'))}>
      <Icon name="arrowLeft" size={18} />
      Назад к новостям
    </button>
  );
}

function fullDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const date = d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).replace(' г.', '');
  return iso.length > 10 ? `${date}, ${d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}` : date;
}

/** Шапка новости: источник с датой, заголовок, картинка (или иллюстрация по теме). */
function NewsHead({ title, publisher, date, factor, image }: { title: string; publisher: string | null; date: string | null; factor: string; image: string | null }) {
  return (
    <>
      <p className="article__source">
        <Icon name="news" size={16} />
        {[publisher, fullDate(date)].filter(Boolean).join(' · ')}
      </p>
      <h1 className="article__title" tabIndex={-1}>
        {title}
      </h1>
      <NewsThumb src={image} factor={factor} size="xl" />
    </>
  );
}

const MENU_NOTE: Partial<Record<CardMenuItem['id'], string>> = {
  weekly: 'Сводки недели в прототипе пока нет.',
  remind: 'Напоминание — в прототипе недоступно: ничего не сохраняется.',
};

function Card({
  insight,
  company,
  personaId,
  eventId,
  item,
  detail,
  steps,
}: {
  insight: Insight;
  company: CompanyProfile;
  personaId: string;
  eventId: string;
  item: FeedItem | null;
  detail: AsyncState<EventDetail | null> & { retry: () => void };
  /** шаги разбора, если он собирался у нас на глазах; пусто — разбор взят готовым */
  steps: AgentStep[];
}) {
  const exposure = useAsync((signal) => api.exposure(company.id, signal), company.id);
  const { hide } = useHidden();
  const navigate = useNavigate();
  const location = useLocation();
  const screen = cardScreen({ insight, item, exposure: exposure.status === 'ok' ? exposure.data : null });
  const index: RefIndex = {
    sources: Object.fromEntries(insight.sources.map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };

  // Из ленты по «Обсудить … с менеджером» форма открыта сразу (без перевода фокуса вниз, мимо новости);
  // перезагрузка и «Назад» её снова не открывают.
  const [arrival] = useState(() => (location.state as { openTarget?: boolean; request?: RequestKind } | null) ?? null);
  const [request, setRequest] = useState<RequestKind | null>(arrival?.openTarget ? (arrival.request ?? 'manager') : null);
  const [round, setRound] = useState(0);
  const [focusForm, setFocusForm] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (arrival) navigate('.', { replace: true, state: null, preventScrollReset: true });
    // только при входе
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Фокус — на вывод, без прокрутки: на узком экране вывод стоит над новостью и должен остаться на виду.
  const verdictRef = useRef<HTMLElement>(null);
  useEffect(() => verdictRef.current?.focus({ preventScroll: true }), []);

  const level = levelWith(item, insight);
  // Заголовок вывода — только вывод модели; нет его — показываем уровень и «почему», без подмены.
  const model = insight.verdict?.headline ?? insight.why_it_matters.find((s) => s.origin === 'ai' && !isHypothesis(s))?.text ?? null;
  const headline = model ? plain(model) : null;
  const whyRaw = insight.verdict?.why ?? insight.why_it_matters.find((s) => s.origin === 'data')?.text;
  const why = whyRaw ? plain(whyRaw) : item ? whyOf(item) : null;
  const todo = (insight.verdict?.actions?.length ? insight.verdict.actions : insight.actions.filter((a) => a.kind !== 'product').map((a) => a.text))
    .slice(0, 3)
    .map(plain);
  const bank = bankOf(insight);
  const claims = claimsOf(insight);
  // Один главный риск и одна возможность — на основном экране, а не за раскрытиями.
  const firstPlain = (list: { text: string; origin: string; confidence?: string | null }[]) => {
    const s = list.find((x) => x.text && x.origin !== 'estimate' && !isHypothesis(x as never));
    return s ? plain(s.text) : null;
  };
  const risk = firstPlain(insight.consequences.risks);
  const chance = firstPlain(insight.consequences.opportunities);
  // Цифры из данных компании (подписи уже без кодов ОКВЭД и без дублей — cardScreen).
  const numbers = screen.forYou.numbers.map((n) => ({ value: n.value, label: plain(n.label) }));
  const topic = screen.target?.topic ?? 'последствия для компании';
  const context = [insight.event.title, headline, bank?.statement].filter(Boolean).join(' · ');
  const quotes = (insight.quotes ?? []).map((q) => q.text);
  const leadNews = insight.sources.find((s) => s.kind === 'news');

  function open(kind: RequestKind) {
    setFocusForm(true);
    setRequest(kind);
    setRound((n) => n + 1);
  }

  function onMenu(id: CardMenuItem['id']) {
    if (id === 'hide') {
      hide(eventId);
      void api.feedback({ insight_id: insight.id, persona_id: personaId, useful: false, reason: 'Скрыт: не про нас' }).catch(() => undefined);
      navigate('/radar');
      return;
    }
    if (id === 'product') {
      open('application');
      return;
    }
    setNote(MENU_NOTE[id] ?? null);
  }

  return (
    <div className="article-page article-page--ready">
      <aside className="verdict side-col appear" aria-label="Что это значит для компании" ref={verdictRef} tabIndex={-1}>
        <section className="card verdict__card">
          <p className={`verdict__level verdict__level--${level}`}>
            <LevelIcon level={level} />
            {LEVEL_LABEL[level]}
          </p>
          {headline && (
            <h2 className="verdict__headline">
              <span className="verdict__ai" title="Вывод модели">
                <Icon name="model" size={16} />
                <span className="visually-hidden">Вывод модели: </span>
              </span>
              {headline}
            </h2>
          )}
          {numbers.length > 0 && (
            <dl className="verdict__numbers">
              {numbers.map((n) => (
                <div key={n.label}>
                  <dt>{n.label}</dt>
                  <dd>{n.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {claims && <ClaimsCheck view={claims} />}
          {bank ? (
            <div className="verdict__bank">
              <p>
                {bank.statement}
                {insight.bank_position?.outdated && <b className="verdict__outdated"> — прогноз устарел</b>}
              </p>
              {insight.bank_position?.outdated && insight.bank_position.outdated_note && (
                <p className="verdict__outdated-note">{capitalize(insight.bank_position.outdated_note)}</p>
              )}
              <span>{bank.caption}</span>
            </div>
          ) : (
            <p className="verdict__nobank">
              <Icon name="bank" size={16} />
              Позиции Альфа-Банка по этой теме нет
            </p>
          )}
          {why && (
            <>
              <p className="caps">Почему</p>
              <p className="verdict__text">{why}</p>
            </>
          )}
          {(risk || chance) && (
            <ul className="verdict__rc">
              {risk && (
                <li className="verdict__rc-item verdict__rc-item--risk">
                  <Icon name="warning" size={16} />
                  <span>
                    <b>Риск:</b> {risk}
                  </span>
                </li>
              )}
              {chance && (
                <li className="verdict__rc-item verdict__rc-item--chance">
                  <Icon name="check" size={16} />
                  <span>
                    <b>Возможность:</b> {chance}
                  </span>
                </li>
              )}
            </ul>
          )}
          {todo.length > 0 && (
            <section className="verdict__todo-box" aria-labelledby="todo-title">
              <h3 className="verdict__todo-title" id="todo-title">
                Что делать
              </h3>
              <ol className="verdict__todo">
                {todo.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ol>
            </section>
          )}
          <div className="verdict__actions">
            <button
              type="button"
              className="btn btn--secondary btn--s"
              aria-expanded={request === 'task'}
              aria-controls={request === 'task' ? 'request-form' : undefined}
              onClick={() => open('task')}
            >
              <Icon name="check" size={16} />
              Поручить
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--s"
              aria-expanded={request === 'forward'}
              aria-controls={request === 'forward' ? 'request-form' : undefined}
              onClick={() => open('forward')}
            >
              <Icon name="forward" size={16} />
              Переслать коллеге
            </button>
          </div>
          <button
            ref={triggerRef}
            type="button"
            className="btn btn--outline btn--block verdict__manager"
            onClick={() => open('manager')}
            aria-expanded={request === 'manager'}
            aria-controls={request === 'manager' ? 'request-form' : undefined}
          >
            <span>{managerLabel(item?.products)}</span>
            <span className="verdict__manager-hint">Менеджер получит разбор и тему: {topic}</span>
          </button>
          {request && (
            <div id="request-form">
              <RequestForm
                key={`${request}-${round}`}
                kind={request}
                topic={
                  request === 'application'
                    ? (insight.actions.find((a) => a.kind === 'product')?.text ?? topic)
                    : request === 'task'
                      ? (todo[0] ?? topic)
                      : topic
                }
                context={context}
                onClose={() => {
                  setRequest(null);
                  triggerRef.current?.focus();
                }}
                focus={focusForm}
              />
            </div>
          )}
          <AskBox insight={insight} personaId={personaId} index={index} topic={topicOf(insight, item)} />
          {steps.length > 0 && (
            <details className="howgot">
              <summary>
                <Icon name="model" size={16} />
                Как получен вывод · {steps.length} {stepsWord(steps.length)}
                <Icon name="chevronDown" size={14} className="howgot__chevron" />
              </summary>
              <ol className="howgot__list">
                {steps.map((st, i) => (
                  <li key={`${i}-${st.title}`}>
                    <Icon name="check" size={14} />
                    {st.title}
                  </li>
                ))}
              </ol>
              {insight.trace_id && (
                <Link to={tracePath(insight.trace_id)} className="link-action">
                  Подробнее: инструменты, источники, проверки
                </Link>
              )}
            </details>
          )}
          <div className="verdict__links">
            {insight.trace_id && steps.length === 0 && (
              <Link to={tracePath(insight.trace_id)} className="chip-link chip-link--plain">
                <Icon name="model" size={16} />
                Как получен вывод
              </Link>
            )}
            <MoreMenu items={screen.menu} onPick={onMenu} />
          </div>
          <p className="side-note-live" aria-live="polite">
            {note}
          </p>
          <FeedbackBox insightId={insight.id} personaId={personaId} />
          <Disclaimer text={screen.disclaimer} />
        </section>

        <ExpandButton open={details} onClick={() => setDetails((v) => !v)} more="Подробнее о разборе" less="Скрыть подробности" />
        {details && (
          <div className="verdict__rows appear">
            {screen.rows
              .filter((r) => r.id !== 'ask' && r.id !== 'trace')
              .map((row) => (
                <Row key={row.id} row={row}>
                  {row.id === 'chain' && <StatementList items={insight.why_it_matters} index={index} />}
                  {row.id === 'risks' && <StatementList items={screen.riskItems} index={index} />}
                  {row.id === 'hypotheses' && <StatementList items={screen.hypotheses} index={index} />}
                  {row.id === 'estimates' &&
                    (screen.estimates.length ? (
                      <StatementList items={screen.estimates} index={index} />
                    ) : (
                      <p className="muted">Расчёта в рублях в этом разборе нет.</p>
                    ))}
                  {row.id === 'sources' && (
                    <ul className="xrow__sources">
                      {insight.sources.map((s) => (
                        <li key={s.id}>
                          <SourceView source={s} />
                        </li>
                      ))}
                    </ul>
                  )}
                </Row>
              ))}
          </div>
        )}
      </aside>
      <article className="card article appear" style={{ animationDelay: '80ms' }}>
        <NewsHead
          title={insight.event.title}
          publisher={leadNews?.publisher ?? item?.source.publisher ?? null}
          date={leadNews?.published_at ?? item?.source.published_at ?? insight.event.date ?? null}
          factor={item?.factors[0]?.code ?? 'industry'}
          image={imageOf(detail, item)}
        />
        <FullText detail={detail} quotes={quotes} lead={leadNews} />
        <RelatedNews eventId={eventId} personaId={personaId} />
      </article>

    </div>
  );
}

function stepsWord(n: number): string {
  const a = n % 100;
  const b = n % 10;
  if (a > 10 && a < 20) return 'шагов';
  if (b === 1) return 'шаг';
  if (b >= 2 && b <= 4) return 'шага';
  return 'шагов';
}

function imageOf(detail: AsyncState<EventDetail | null>, item: FeedItem | null): string | null {
  const d = detail.status === 'ok' ? detail.data : null;
  return d?.image_url ?? d?.source?.image_url ?? item?.image_url ?? null;
}

/** Карточка события — макеты «A+ · Новость целиком» и «A+ · Ход разбора». */
export function CardPage() {
  const { eventId = '' } = useParams();
  const { persona, company } = useCurrentUser();
  const { load, retry } = useInsight(eventId, persona.id);
  const briefing = useBriefing();
  const item = briefing.status === 'ok' ? (briefing.data.items.find((i) => i.event_id === eventId) ?? null) : null;
  // Новость грузится сразу и отдельно от разбора: её видно, пока разбор собирается.
  const detail = useAsync((signal) => api.eventDetail(eventId, signal), eventId);
  const d = detail.status === 'ok' ? detail.data : null;

  // Шаги разбора, которые прошли у нас на глазах, — для «Как получен вывод · N шагов» после готовности.
  const [seen, setSeen] = useState<{ key: string; steps: AgentStep[] }>({ key: '', steps: [] });
  const key = `${eventId}|${persona.id}`;
  if (load.status === 'building') {
    const now = stepsOf(load.job);
    if (seen.key !== key || seen.steps.length !== now.length || seen.steps.at(-1)?.title !== now.at(-1)?.title) setSeen({ key, steps: now });
  }
  const doneSteps = seen.key === key ? seen.steps.map((st) => ({ ...st, state: 'done' as const })) : [];

  useEffect(() => markRead(persona.id, eventId), [persona.id, eventId]);

  return (
    <div className="page article-wrap">
      <BackToNews />
      {(load.status === 'loading' || load.status === 'building') && (
        <div className="article-page">
          <div className="side-col side-col--live">
            <Thinking
              steps={stepsOf(load.status === 'building' ? load.job : null)}
              progress={
                load.status === 'building'
                  ? progressOf(stepsOf(load.job), load.job.steps_total, load.job.elapsed_s, load.job.status === 'queued')
                  : 'Запрашиваю разбор'
              }
            />
          </div>
          <article className="card article">
            {item || d?.source?.title ? (
              <NewsHead
                title={item?.event.title ?? d?.source?.title ?? ''}
                publisher={item?.source.publisher ?? d?.source?.publisher ?? null}
                date={item?.source.published_at ?? d?.source?.published_at ?? item?.event.date ?? null}
                factor={item?.factors[0]?.code ?? 'industry'}
                image={imageOf(detail, item)}
              />
            ) : (
              detail.status === 'loading' && <Skeleton width="80%" height={28} />
            )}
            <FullText detail={detail} quotes={[]} />
          </article>
        </div>
      )}
      {load.status === 'error' &&
        (load.canRetry ? (
          <ErrorState title="Не удалось собрать разбор" error={new Error(load.message)} onRetry={retry} />
        ) : (
          <EmptyState title="Разбор сейчас не собрать">
            {load.message}. <Link to="/radar">Вернуться к новостям</Link>
          </EmptyState>
        ))}
      {load.status === 'none' && (
        <EmptyState title="Это событие не касается выбранной компании">
          Для роли «{roleLabel[persona.role].toLowerCase()}» в компании «{company.display_name}» связи с событием не
          нашлось. <Link to="/radar">Вернуться к новостям</Link>
        </EmptyState>
      )}
      {load.status === 'ready' && (
        <Card insight={load.insight} company={company} personaId={persona.id} eventId={eventId} item={item} detail={detail} steps={doneSteps} />
      )}
    </div>
  );
}
