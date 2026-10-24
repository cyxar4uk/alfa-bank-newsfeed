import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { CompanyProfile, Insight } from '../api/types';
import { AskBox } from '../components/AskBox';
import { Disclaimer } from '../components/Disclaimer';
import { FeedbackBox } from '../components/FeedbackBox';
import { Icon } from '../components/Icon';
import { MoreMenu } from '../components/MoreMenu';
import { PrototypeNote } from '../components/PrototypeNote';
import { SourceMark } from '../components/SourceMark';
import { SourceView, StatementList, type RefIndex } from '../components/Statement';
import { EmptyState, ErrorState } from '../components/States';
import { TargetAction } from '../components/TargetAction';
import { useBriefing } from '../state/briefing';
import { useHidden } from '../state/hidden';
import { roleLabel } from '../state/labels';
import { tracePath } from '../state/routes';
import { cardScreen, TARGET_DELAY_MS, type CardMenuItem, type CardRow } from '../state/screens';
import { useCurrentUser } from '../state/session';
import { useAsync } from '../state/useAsync';
import { useInsight } from '../state/useInsight';

function Building({ stage, done, eta }: { stage: string; done: string[]; eta: number | null }) {
  return (
    <div className="card building" aria-live="polite">
      <p className="building__title">Собираем разбор для вашей компании</p>
      <ol className="building__steps">
        {done.map((s, i) => (
          <li key={`${i}-${s}`} className="building__step building__step--done">
            <Icon name="check" size={16} />
            {s}
          </li>
        ))}
        {stage && <li className="building__step building__step--now">{stage}…</li>}
      </ol>
      {eta != null && eta > 0 && <p className="muted">Осталось примерно {Math.ceil(eta)} с</p>}
    </div>
  );
}

function Row({ row, children }: { row: CardRow; children: ReactNode }) {
  return (
    <details className="xrow">
      <summary>
        <span className="xrow__text">
          <span className="xrow__title">{row.title}</span>
          <span className="xrow__summary">{row.summary}</span>
        </span>
        <Icon name="chevronRight" size={18} className="xrow__chevron" />
      </summary>
      <div className="xrow__body">{children}</div>
    </details>
  );
}

// В прототипе эти действия ничего не делают — так и говорим, не изображая результат.
const MENU_DONE: Partial<Record<CardMenuItem['id'], string>> = {
  forward: 'Переслать коллеге — в прототипе недоступно: ничего не отправляется.',
  weekly: 'Добавить в сводку недели — в прототипе недоступно: сводки недели пока нет.',
  remind: 'Напоминание — в прототипе недоступно: ничего не сохраняется.',
};

function Card({ insight, company, personaId, eventId }: { insight: Insight; company: CompanyProfile; personaId: string; eventId: string }) {
  const briefing = useBriefing();
  const exposure = useAsync((signal) => api.exposure(company.id, signal), company.id);
  const { hide } = useHidden();
  const navigate = useNavigate();
  const item = briefing.status === 'ok' ? (briefing.data.items.find((i) => i.event_id === eventId) ?? null) : null;
  const screen = useMemo(
    () => cardScreen({ insight, item, exposure: exposure.status === 'ok' ? exposure.data : null }),
    [insight, item, exposure],
  );
  const index: RefIndex = {
    sources: Object.fromEntries(insight.sources.map((s) => [s.id, s])),
    features: Object.fromEntries(company.features.map((f) => [f.id, f])),
  };

  // Целевое действие — через ~15 с на посте или когда дочитали карточку до конца; из ленты по кнопке
  // «Обсудить с менеджером» — сразу открытым.
  const location = useLocation();
  const [openTarget] = useState(() => Boolean((location.state as { openTarget?: boolean } | null)?.openTarget));
  const [due, setDue] = useState(openTarget);
  useEffect(() => {
    // Перезагрузка и «Назад» не должны снова открывать обращение.
    if (openTarget) navigate('.', { replace: true, state: null, preventScrollReset: true });
    // только при входе
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [productForm, setProductForm] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const endRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const timer = setTimeout(() => setDue(true), TARGET_DELAY_MS);
    const end = endRef.current;
    const observer =
      end && 'IntersectionObserver' in window
        ? new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setDue(true))
        : null;
    // На первом экране конец карточки виден сразу — считаем «дочитал» только после прокрутки.
    const onScroll = () => end && observer?.observe(end);
    window.addEventListener('scroll', onScroll, { once: true });
    return () => {
      clearTimeout(timer);
      observer?.disconnect();
      window.removeEventListener('scroll', onScroll);
    };
  }, []);

  function onMenu(id: CardMenuItem['id']) {
    if (id === 'hide') {
      hide(eventId);
      void api.feedback({ insight_id: insight.id, persona_id: personaId, useful: false, reason: 'Скрыт: не про нас' }).catch(() => undefined);
      navigate('/radar');
      return;
    }
    if (id === 'product') {
      setProductForm(true);
      setDue(true);
      return;
    }
    setNotice(MENU_DONE[id] ?? null);
  }

  const context = [insight.event.title, screen.forYou.phrase, screen.forYou.quote?.text].filter(Boolean).join(' · ');
  const target = productForm
    ? { prompt: 'Проверить условия продукта банка?', button: 'Оставить заявку', topic: 'условия продукта банка' }
    : due
      ? (screen.target ??
        (openTarget ? { prompt: 'Обсудить разбор с менеджером?', button: 'Обсудить с менеджером', topic: 'последствия для компании' } : null))
      : null;
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => titleRef.current?.focus(), []);

  return (
    <div className="card-page">
      <article className="card-main">
        <div className="card-main__crumbs">
          <Link to="/radar" className="card-main__crumb">
            {screen.crumbs}
          </Link>
          <MoreMenu items={screen.menu} onPick={onMenu} />
        </div>
        <h1 className="card-main__title" tabIndex={-1} ref={titleRef}>
          {screen.title}
        </h1>
        {screen.sources.length > 0 && (
          <ul className="card-main__sources">
            {screen.sources.map((s) => (
              <li key={s.label}>
                <SourceMark mark={s.mark} />
                {s.label}
              </li>
            ))}
          </ul>
        )}
        {screen.lead.length > 0 && <p className="card-main__lead">{screen.lead.join(' ')}</p>}

        <section className="for-you-card" aria-labelledby="for-you-title">
          <p className="caps" id="for-you-title">
            Что это значит для вас
          </p>
          <p className="for-you-card__phrase">{screen.forYou.phrase}</p>
          {screen.forYou.numbers.length > 0 && (
            <dl className="for-you-card__numbers">
              {screen.forYou.numbers.map((n) => (
                <div key={n.label}>
                  <dt>{n.label}</dt>
                  <dd>{n.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {screen.forYou.quote?.verbatim && (
            <figure className="bank-quote">
              <blockquote className="bank-quote__text">{screen.forYou.quote.text}</blockquote>
              <figcaption className="bank-quote__caption">{screen.forYou.quote.caption}</figcaption>
            </figure>
          )}
          {screen.forYou.quote && !screen.forYou.quote.verbatim && (
            <div className="bank-quote">
              <p className="bank-quote__text">Позиция банка: {screen.forYou.quote.text}</p>
              <p className="bank-quote__caption">{screen.forYou.quote.caption}</p>
            </div>
          )}
          {!screen.forYou.quote && (
            <p className="bank-quote__none">Позиции Альфа-Банка по теме нет.</p>
          )}
        </section>

        <div aria-live="polite">
          {notice && (
            <p className="card-main__notice">
              <Icon name="info" size={16} />
              {notice}
            </p>
          )}
          {target && <p className="visually-hidden">{target.prompt}</p>}
        </div>
        {target && (
          <TargetAction
            key={productForm ? 'product' : 'target'}
            prompt={target.prompt}
            button={target.button}
            topic={target.topic}
            context={context}
            openForm={productForm || openTarget}
          />
        )}
        <span ref={endRef} aria-hidden="true" />
      </article>

      <aside className="card-rail" aria-label="Подробнее о разборе">
        <p className="caps">Подробнее о разборе</p>
        {screen.rows.map((row) => (
          <Row key={row.id} row={row}>
            {row.id === 'chain' && <StatementList items={insight.why_it_matters} index={index} />}
            {row.id === 'risks' && (
              <StatementList items={screen.riskItems} index={index} />
            )}
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
            {row.id === 'trace' && insight.trace_id && (
              <Link to={tracePath(insight.trace_id)} className="link-action">
                Открыть шаги агента →
              </Link>
            )}
            {row.id === 'ask' && <AskBox insight={insight} personaId={personaId} index={index} />}
          </Row>
        ))}
        <FeedbackBox insightId={insight.id} personaId={personaId} />
        <Disclaimer text={screen.disclaimer} />
      </aside>
    </div>
  );
}

/** Карточка события (макет «Итог · 02/03»): первый экран без прокрутки, подробности — в правой колонке. */
export function CardPage() {
  const { eventId = '' } = useParams();
  const { persona, company } = useCurrentUser();
  const { load, retry } = useInsight(eventId, persona.id);

  return (
    <div className="page">
      {load.status === 'loading' && <Building stage="Запрашиваем разбор" done={[]} eta={null} />}
      {load.status === 'building' && (
        <Building
          stage={load.job.status === 'queued' ? `В очереди${load.job.queue_position ? `: ${load.job.queue_position}-й` : ''}` : load.job.stage}
          done={load.job.stages_done}
          eta={load.job.eta_s}
        />
      )}
      {load.status === 'error' &&
        (load.canRetry ? (
          <ErrorState title="Не удалось собрать разбор" error={new Error(load.message)} onRetry={retry} />
        ) : (
          <EmptyState title="Разбор сейчас не собрать">
            {load.message}. <Link to="/radar">Вернуться к ленте</Link>
          </EmptyState>
        ))}
      {load.status === 'none' && (
        <EmptyState title="Это событие не касается выбранной компании">
          Для роли «{roleLabel[persona.role].toLowerCase()}» в компании «{company.display_name}» связи с событием не
          нашлось. <Link to="/radar">Вернуться к ленте</Link>
        </EmptyState>
      )}
      {load.status === 'ready' && <Card insight={load.insight} company={company} personaId={persona.id} eventId={eventId} />}
      <PrototypeNote />
    </div>
  );
}
