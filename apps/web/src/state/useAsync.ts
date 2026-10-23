import { useCallback, useEffect, useState } from 'react';

export type AsyncState<T> =
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'error'; error: Error };

/**
 * Загрузка с повтором. `key` — от чего зависит запрос; смена ключа перезапускает его и отменяет прежний,
 * чтобы при быстрой смене пользователя или события не висели лишние запросы.
 */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, key: string) {
  const [result, setResult] = useState<{ key: string; attempt: number; state: AsyncState<T> } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => !controller.signal.aborted && setResult({ key, attempt, state: { status: 'ok', data } }),
      (error: unknown) =>
        !controller.signal.aborted &&
        setResult({
          key,
          attempt,
          state: { status: 'error', error: error instanceof Error ? error : new Error(String(error)) },
        }),
    );
    return () => controller.abort();
    // load пересоздаётся на каждом рендере; запрос зависит только от key и попытки
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  // Пока ответ не пришёл для текущего ключа и попытки — показываем загрузку.
  const state: AsyncState<T> =
    result && result.key === key && result.attempt === attempt ? result.state : { status: 'loading' };

  return { ...state, retry } as AsyncState<T> & { retry: () => void };
}
