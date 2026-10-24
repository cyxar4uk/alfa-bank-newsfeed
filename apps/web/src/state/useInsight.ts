import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { Insight, JobStatus } from '../api/types';

export type InsightLoad =
  | { status: 'loading' }
  | { status: 'building'; job: JobStatus }
  | { status: 'ready'; insight: Insight }
  | { status: 'none' }
  /** canRetry: false — повтор не поможет (события нет, бюджет моделей на сегодня исчерпан) */
  | { status: 'error'; message: string; canRetry: boolean };

const POLL_MS = 1500;
/** Сколько подряд сбоев опроса статуса терпим: сборка на сервере идёт, сеть могла моргнуть. */
const POLL_FAILURES = 3;

function toError(e: unknown): InsightLoad {
  const message = e instanceof Error ? e.message : String(e);
  const final = e instanceof ApiError && (e.status === 404 || (e.status === 503 && /бюджет/i.test(message)));
  return { status: 'error', message, canRetry: !final };
}

/**
 * Разбор без долгого ожидания: API отвечает 202 и собирает карточку в фоне, мы раз в 1,5 с спрашиваем статус и
 * показываем этапы. При done забираем готовую карточку, при failed — текст ошибки и «Повторить».
 */
export function useInsight(eventId: string, personaId: string) {
  const key = `${eventId}|${personaId}`;
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; attempt: number; load: InsightLoad } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const set = (load: InsightLoad) => !signal.aborted && setResult({ key, attempt, load });

    const poll = () => {
      if (signal.aborted) return;
      timer = setTimeout(() => {
        api.insightStatus(eventId, personaId, signal).then(
          (job) => {
            if (signal.aborted) return;
            failures = 0;
            if (job.status === 'done') void start();
            else if (job.status === 'failed')
              set({ status: 'error', message: job.error || 'Разбор собрать не удалось', canRetry: true });
            else {
              set({ status: 'building', job });
              poll();
            }
          },
          (e: unknown) => {
            if (signal.aborted) return;
            failures += 1;
            if (failures < POLL_FAILURES && !(e instanceof ApiError && e.status === 404)) poll();
            else set(toError(e));
          },
        );
      }, POLL_MS);
    };

    const start = () =>
      api.insightJob(eventId, personaId, signal).then(
        (r) => {
          if (signal.aborted) return;
          if (r.kind === 'ready') set({ status: 'ready', insight: r.insight });
          else if (r.kind === 'none') set({ status: 'none' });
          else {
            set({ status: 'building', job: r.job });
            poll();
          }
        },
        (e: unknown) => set(toError(e)),
      );

    void start();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [key, attempt, eventId, personaId]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const load: InsightLoad = result && result.key === key && result.attempt === attempt ? result.load : { status: 'loading' };
  return { load, retry };
}
