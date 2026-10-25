import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { CatalogSource } from '../api/types';
import { Disclaimer } from '../components/Disclaimer';
import { Icon } from '../components/Icon';
import { ServiceTabs } from '../components/ServiceTabs';
import { ChipSwitch } from '../components/WeekParts';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { useBriefing } from '../state/briefing';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

function metaOf(s: CatalogSource): string {
  return [s.country === 'intl' ? 'Мир' : 'Россия', s.access || (s.kind === 'paid_api' ? 'по подписке · через API' : 'бесплатно')].join(' · ');
}

/** Что появится в ленте после подключения: темы источника, если они есть в каталоге. */
function connectedNote(source: CatalogSource): string {
  if (source.benefit) return `Подключён. ${source.benefit}`;
  const topics = (source.topics ?? []).slice(0, 3);
  return topics.length > 0
    ? `Подключён — в ленте появятся новости ${source.name}: ${topics.join(', ')}.`
    : `Подключён — в ленте появятся новости ${source.name}.`;
}

function SourceCard({
  source,
  open,
  onOpen,
  connected,
  onToggle,
  personaId,
}: {
  personaId: string;
  source: CatalogSource;
  open: boolean;
  onOpen: () => void;
  connected: boolean;
  onToggle: (connected: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [iconFailed, setIconFailed] = useState(false);
  const paid = source.kind === 'paid_api';

  function connect() {
    setBusy(true);
    setError(null);
    api
      .connectSource(source.id, personaId)
      .then((res) => {
        onToggle(true);
        setMessage(res?.message || connectedNote(source));
      })
      .catch(() => setError('Не удалось подключить — попробуйте ещё раз.'))
      .finally(() => setBusy(false));
  }

  function disconnect() {
    setBusy(true);
    setError(null);
    api
      .disconnectSource(source.id, personaId)
      .then((res) => {
        onToggle(false);
        setMessage(
          res
            ? res.message || `Отключён — новостей ${source.name} в ленте больше не будет.`
            : `Отключён на этом экране — в прототипе сервер пока не запоминает отключение.`,
        );
      })
      .catch(() => setError('Не удалось отключить — попробуйте ещё раз.'))
      .finally(() => setBusy(false));
  }

  return (
    <li className="source-card appear">
      <div className="source-card__head">
        <span className="source-card__icon">
          {source.icon_url && !iconFailed ? (
            <img src={source.icon_url} alt="" onError={() => setIconFailed(true)} />
          ) : (
            <Icon name={source.country === 'intl' ? 'ved' : 'news'} size={20} />
          )}
        </span>
        <div className="source-card__text">
          <p className="source-card__name">{source.name}</p>
          <p className="source-card__meta">{metaOf(source)}</p>
        </div>
      </div>
      {source.about ? (
        <p className="source-card__topics">{source.about}</p>
      ) : (
        source.topics && source.topics.length > 0 && <p className="source-card__topics">{source.topics.join(', ')}</p>
      )}
      {source.benefit && <p className="source-card__gives">{source.benefit}</p>}
      {/* note для руководителя — только в новом каталоге (#78); в старом это заметки команды, их не показываем */}
      {source.note && source.can_disconnect !== undefined && <p className="source-card__note">{source.note}</p>}
      {connected ? (
        <div className="source-card__state">
          <span className="status-ok">
            <Icon name="check" size={16} />
            Подключён
          </span>
          {source.can_disconnect !== false && (
            <button type="button" className="link-button source-card__off" disabled={busy} onClick={disconnect}>
              Отключить<span className="visually-hidden"> {source.name}</span>
            </button>
          )}
        </div>
      ) : paid ? (
        <button type="button" className="btn btn--outline btn--s" aria-expanded={open} aria-controls="howto" onClick={onOpen}>
          {open ? 'Скрыть инструкцию' : 'Подключить по API'}
        </button>
      ) : (
        <button type="button" className="btn btn--secondary btn--s" disabled={busy} onClick={connect}>
          Подключить<span className="visually-hidden"> {source.name}</span>
        </button>
      )}
      <p className="source-card__message" role="status">
        {message}
      </p>
      {error && (
        <p className="source-card__error" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** Как подключить платный источник по API: шаги издателя; ключ в прототипе не принимаем. */
function HowTo({ source, onDone }: { source: CatalogSource; onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  // Открыли инструкцию — показываем её сразу: прокрутка к ней и фокус на заголовок.
  useEffect(() => {
    titleRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    titleRef.current?.focus({ preventScroll: true });
  }, [source.id]);
  return (
    <section className="card howto appear" id="howto" aria-labelledby="howto-title">
      <h2 className="howto__title" id="howto-title" ref={titleRef} tabIndex={-1}>
        <Icon name="key" size={20} />
        Как подключить {source.name} по API
      </h2>
      {(source.benefit || source.about) && <p className="howto__benefit">{source.benefit ?? source.about}</p>}
      <ol className="howto__steps">
        {[
          'Оформите подписку на новостной API у издателя.',
          'В личном кабинете издателя создайте ключ доступа к API.',
          'Передайте ключ администратору вашей компании — он добавит его в настройки сервиса.',
        ].map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
      <p className="muted">В прототипе ключи не принимаем.</p>
      {error && (
        <p className="source-card__error" role="alert">
          Не удалось отметить — попробуйте ещё раз.
        </p>
      )}
      <div className="howto__actions">
        <button
          type="button"
          className="btn btn--graphite btn--s"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(false);
            onDone()
              .catch(() => setError(true))
              .finally(() => setBusy(false));
          }}
        >
          Отметить как подключённый
        </button>
        {source.docs_url && (
          <a href={source.docs_url} target="_blank" rel="noreferrer" className="link-action">
            Документация издателя
          </a>
        )}
      </div>
    </section>
  );
}

/** «Источники» (макет «A+ · Источники»): своя новость — наверху; пул важных для бизнеса источников, подключение и отключение. */
export function SourcesPage() {
  const { persona } = useCurrentUser();
  const catalog = useAsync((signal) => api.catalog(persona.id, signal), `catalog|${persona.id}`);
  const briefing = useBriefing();
  const navigate = useNavigate();
  const [openId, setOpenId] = useState<string | null>(null);
  const [connected, setConnected] = useState<Record<string, boolean>>({});
  const [input, setInput] = useState('');
  const [view, setView] = useState<'all' | 'relevant' | 'connected'>('all');

  // Каталога в API может ещё не быть — тогда честно показываем издания, которые уже приходят в ленту.
  const fromFeed: CatalogSource[] =
    briefing.status === 'ok'
      ? [...new Set(briefing.data.items.map((i) => i.source.publisher).filter((p): p is string => Boolean(p)))].map((name) => ({
          id: name,
          name,
          country: 'ru',
          kind: 'free',
          connected: true,
        }))
      : [];
  // Каталог пустой или его ещё нет в API — издания из ленты; пока лента грузится — заготовки.
  const list = catalog.status === 'ok' ? (catalog.data?.length ? catalog.data : fromFeed) : [];
  const waiting = catalog.status === 'loading' || (catalog.status === 'ok' && !catalog.data?.length && briefing.status === 'loading');
  const open = list.find((s) => s.id === openId) ?? null;
  const isConnected = (s: CatalogSource) => connected[s.id] ?? s.connected;
  // «Для вашей отрасли» — только если каталог знает, какие источники пишут об отрасли компании.
  const hasRelevant = list.some((s) => s.for_your_industry === true);
  const shown = list.filter((s) =>
    view === 'relevant' ? s.for_your_industry === true : view === 'connected' ? isConnected(s) : true,
  );
  const views: { value: typeof view; label: string }[] = [
    { value: 'all', label: 'Все' },
    ...(hasRelevant ? [{ value: 'relevant' as const, label: 'Для вашей отрасли' }] : []),
    { value: 'connected', label: 'Подключённые' },
  ];

  function onAnalyze(e: FormEvent) {
    e.preventDefault();
    navigate('/radar/analyze', { state: { input } });
  }

  return (
    <div className="page news-page">
      <ServiceTabs />
      <section className="card own-news-card" aria-labelledby="own-news-title">
        <h2 className="own-news-card__title" id="own-news-title">
          <Icon name="model" size={20} />
          Своя новость
        </h2>
        <p className="own-news-card__lead">Вставьте ссылку или текст — разберём, что это значит для компании.</p>
        <form className="own-news" onSubmit={onAnalyze}>
          <Icon name="search" size={18} />
          <label htmlFor="own-news" className="visually-hidden">
            Своя новость: ссылка или текст
          </label>
          <input id="own-news" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ссылка на новость или её текст" />
          <button type="submit" className="btn btn--primary btn--s" disabled={!input.trim()}>
            Разобрать
          </button>
        </form>
      </section>

      <p className="sources-lead">Подключите источники, которые важны для вашего бизнеса. Чем больше надёжных источников, тем точнее выводы.</p>

      {waiting && (
        <ul className="source-grid" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <li key={i} className="source-card">
              <Skeleton width="60%" height={18} />
              <Skeleton width="90%" />
            </li>
          ))}
        </ul>
      )}
      {catalog.status === 'error' && <ErrorState title="Не удалось загрузить источники" error={catalog.error} onRetry={catalog.retry} />}
      {catalog.status === 'ok' && !waiting && list.length === 0 && (
        <EmptyState title="Источников пока нет">Они появятся, когда загрузится лента новостей.</EmptyState>
      )}
      {list.length > 0 && (
        <ChipSwitch label="Какие источники показать" value={view} options={views} onChange={setView} />
      )}
      {list.length > 0 && shown.length === 0 && <p className="muted">Здесь пока пусто.</p>}
      {shown.length > 0 && (
        <ul className="source-grid">
          {shown.map((s) => (
            <SourceCard
              key={s.id}
              source={s}
              open={openId === s.id}
              onOpen={() => setOpenId(openId === s.id ? null : s.id)}
              connected={isConnected(s)}
              onToggle={(on) => setConnected((c) => ({ ...c, [s.id]: on }))}
              personaId={persona.id}
            />
          ))}
        </ul>
      )}
      {open && !isConnected(open) && (
        <HowTo
          source={open}
          onDone={() =>
            api.connectSource(open.id, persona.id).then(() => {
              setConnected((c) => ({ ...c, [open.id]: true }));
              setOpenId(null);
            })
          }
        />
      )}

      <Disclaimer />
    </div>
  );
}
