import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { CatalogSource } from '../api/types';
import { Disclaimer } from '../components/Disclaimer';
import { Icon } from '../components/Icon';
import { ServiceTabs } from '../components/ServiceTabs';
import { EmptyState, ErrorState, Skeleton } from '../components/States';
import { useBriefing } from '../state/briefing';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';

function metaOf(s: CatalogSource): string {
  return [s.country === 'intl' ? 'Мир' : 'Россия', s.kind === 'paid_api' ? 'по подписке · через API' : 'бесплатно'].join(' · ');
}

function SourceCard({
  source,
  open,
  onOpen,
  connected,
  onConnected,
  personaId,
}: {
  personaId: string;
  source: CatalogSource;
  open: boolean;
  onOpen: () => void;
  connected: boolean;
  onConnected: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [iconFailed, setIconFailed] = useState(false);
  const paid = source.kind === 'paid_api';
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
      {source.topics && source.topics.length > 0 && <p className="source-card__topics">{source.topics.join(', ')}</p>}
      {source.note && <p className="source-card__topics">{source.note}</p>}
      {connected ? (
        <span className="status-ok">
          <Icon name="check" size={16} />
          Подключён
        </span>
      ) : paid ? (
        <button type="button" className="btn btn--outline btn--s" aria-expanded={open} onClick={onOpen}>
          Подключить по API
        </button>
      ) : (
        <button
          type="button"
          className="btn btn--secondary btn--s"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(false);
            api
              .connectSource(source.id, personaId)
              .then(onConnected)
              .catch(() => setError(true))
              .finally(() => setBusy(false));
          }}
        >
          Подключить
        </button>
      )}
      {error && (
        <p className="source-card__error" role="alert">
          Не удалось подключить — попробуйте ещё раз.
        </p>
      )}
    </li>
  );
}

/** Как подключить платный источник по API: шаги издателя; ключ в прототипе не принимаем. */
function HowTo({ source, onDone }: { source: CatalogSource; onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  return (
    <section className="card howto appear" aria-labelledby="howto-title">
      <h2 className="howto__title" id="howto-title">
        <Icon name="key" size={20} />
        Как подключить {source.name} по API
      </h2>
      <ol className="howto__steps">
        {(source.how_to_connect?.length
          ? source.how_to_connect
          : [
              'Оформите подписку на новостной API у издателя.',
              'В личном кабинете издателя создайте ключ доступа к API.',
              'Передайте ключ администратору вашей компании — он добавит его в настройки сервиса.',
            ]
        ).map((s) => (
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

/** «Источники» (макет «A+ · Источники»): пул важных для бизнеса источников и подключение; своя новость — внизу. */
export function SourcesPage() {
  const { persona } = useCurrentUser();
  const catalog = useAsync((signal) => api.catalog(persona.id, signal), `catalog|${persona.id}`);
  const briefing = useBriefing();
  const navigate = useNavigate();
  const [openId, setOpenId] = useState<string | null>(null);
  const [connected, setConnected] = useState<Record<string, boolean>>({});
  const [input, setInput] = useState('');

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

  function onAnalyze(e: FormEvent) {
    e.preventDefault();
    navigate('/radar/analyze', { state: { input } });
  }

  return (
    <div className="page news-page">
      <ServiceTabs />
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
        <ul className="source-grid">
          {list.map((s) => (
            <SourceCard
              key={s.id}
              source={s}
              open={openId === s.id}
              onOpen={() => setOpenId(openId === s.id ? null : s.id)}
              connected={isConnected(s)}
              onConnected={() => setConnected((c) => ({ ...c, [s.id]: true }))}
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

      <form className="own-news" onSubmit={onAnalyze}>
        <Icon name="search" size={18} />
        <label htmlFor="own-news" className="visually-hidden">
          Своя новость: ссылка или текст
        </label>
        <input
          id="own-news"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Есть своя новость? Вставьте ссылку или текст — разберём для компании"
        />
        <button type="submit" className="btn btn--secondary btn--s" disabled={!input.trim()}>
          Разобрать
        </button>
      </form>
      <Disclaimer />
    </div>
  );
}
