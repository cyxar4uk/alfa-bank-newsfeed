import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { CompanyProfile, FeedItem, Insight } from '../api/types';
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
import { useAsync } from '../state/useAsync';
import { useInsight } from '../state/useInsight';

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
  forward: 'Переслать коллеге — в прототипе недоступно: ничего не отправляется.',
  weekly: 'Сводки недели в прототипе пока нет.',
  remind: 'Напоминание — в прототипе недоступно: ничего не сохраняется.',
};

function Card({
  insight,
  company,
  personaId,
  eventId,
  item,
}: {
  insight: Insight;
  company: CompanyProfile;
  personaId: string;
  eventId: string;
  item: FeedItem | null;
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
    <div className="article-page">
      <aside className="verdict appear" aria-label="Что это значит для компании" ref={verdictRef} tabIndex={-1}>
        <section className="card verdict__card">
          <p className={`verdict__level verdict__level--${level}`}>
            <LevelIcon level={level} />
            {LEVEL_LABEL[level]} для компании
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
          {bank ? (
            <div className="verdict__bank">
              <p>{bank.statement}</p>
              <span>{bank.caption}</span>
            </div>
          ) : (
            <p className="verdict__nobank">
              <Icon name="bank" size={16} />
              Позиции Альфа-Банка по этой теме нет
            </p>
          )}
          <button
            ref={triggerRef}
            type="button"
            className="btn btn--primary btn--block"
            onClick={() => open('manager')}
            aria-expanded={request !== null}
            aria-controls={request ? 'request-form' : undefined}
          >
            Обсудить с менеджером
          </button>
          {request && (
            <div id="request-form">
              <RequestForm
                key={`${request}-${round}`}
                kind={request}
                topic={request === 'application' ? (insight.actions.find((a) => a.kind === 'product')?.text ?? topic) : topic}
                context={context}
                onClose={() => {
                  setRequest(null);
                  triggerRef.current?.focus();
                }}
                focus={focusForm}
              />
            </div>
          )}
          {why && (
            <>
              <p className="caps">Почему</p>
              <p className="verdict__text">{why}</p>
            </>
          )}
          {todo.length > 0 && (
            <>
              <p className="caps">Что делать</p>
              <ol className="verdict__todo">
                {todo.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ol>
            </>
          )}
          <div className="verdict__links">
            {insight.trace_id && (
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
          image={item?.image_url ?? null}
        />
        <FullText eventId={eventId} quotes={quotes} lead={leadNews} />
        <div className="discuss">
          <AskBox insight={insight} personaId={personaId} index={index} />
        </div>
      </article>

    </div>
  );
}

/** Карточка события — макеты «A+ · Новость целиком» и «A+ · Ход разбора». */
export function CardPage() {
  const { eventId = '' } = useParams();
  const { persona, company } = useCurrentUser();
  const { load, retry } = useInsight(eventId, persona.id);
  const briefing = useBriefing();
  const item = briefing.status === 'ok' ? (briefing.data.items.find((i) => i.event_id === eventId) ?? null) : null;

  return (
    <div className="page article-wrap">
      <BackToNews />
      {(load.status === 'loading' || load.status === 'building') && (
        <div className="article-page">
          <article className="card article">
            {item ? (
              <NewsHead
                title={item.event.title}
                publisher={item.source.publisher ?? null}
                date={item.source.published_at ?? item.event.date ?? null}
                factor={item.factors[0]?.code ?? 'industry'}
                image={item.image_url ?? null}
              />
            ) : (
              <Skeleton width="80%" height={28} />
            )}
            <div className="article__wait" aria-hidden="true">
              <Skeleton width="100%" />
              <Skeleton width="96%" />
              <Skeleton width="80%" />
              <Skeleton width="60%" />
            </div>
            <p className="fulltext__note">Вывод появится, когда разбор закончится.</p>
          </article>
          <Thinking job={load.status === 'building' ? load.job : null} />
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
      {load.status === 'ready' && <Card insight={load.insight} company={company} personaId={persona.id} eventId={eventId} item={item} />}
    </div>
  );
}
