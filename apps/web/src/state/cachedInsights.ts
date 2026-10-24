import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Insight } from '../api/types';

/**
 * Уже собранные разборы по событиям — только из кэша API: сначала статус (готово / не запускалось), и лишь для
 * готовых — сам разбор. Новую сборку здесь не запускаем: это платные вызовы моделей.
 */
export function useCachedInsights(eventIds: string[], personaId: string): Record<string, Insight> {
  const key = `${personaId}|${eventIds.join(',')}`;
  const [result, setResult] = useState<{ key: string; insights: Record<string, Insight> }>({ key: '', insights: {} });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const ids = key.split('|')[1]?.split(',').filter(Boolean) ?? [];
    Promise.all(
      ids.map(async (id) => {
        try {
          const job = await api.insightStatus(id, personaId, signal);
          if (job.status !== 'done') return null;
          const r = await api.insightJob(id, personaId, signal);
          return r.kind === 'ready' ? ([id, r.insight] as const) : null;
        } catch {
          return null; // не собирался или ошибка — просто без разбора
        }
      }),
    ).then((pairs) => {
      if (!signal.aborted) setResult({ key, insights: Object.fromEntries(pairs.filter((p) => p !== null)) });
    });
    return () => controller.abort();
  }, [key, personaId]);

  return result.key === key ? result.insights : {};
}
