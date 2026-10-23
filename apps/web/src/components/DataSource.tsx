import { api, ApiError, dataMode, liveMethods } from '../api/client';
import { useAsync } from '../state/useAsync';

const METHOD_LABEL: Record<string, string> = {
  personas: 'пользователи',
  company: 'профили компаний',
  briefing: 'брифинг',
  insight: 'разборы',
  exposureMap: 'карта',
  weekly: 'сводка',
  ask: 'вопросы',
  trace: 'трассы',
  analyze: 'своя новость',
};

/** Откуда данные на экране: честно говорим, что из API, а что тестовое. */
export function DataSource() {
  const health = useAsync((signal) => api.health(signal), 'health');

  if (dataMode === 'mock') return <p className="data-source">Данные: тестовые, без API</p>;

  const live = liveMethods
    .map((m) => METHOD_LABEL[m])
    .filter(Boolean)
    .join(', ');
  const status =
    health.status === 'loading'
      ? 'проверяем API'
      : health.status === 'error'
        ? health.error instanceof ApiError && health.error.status === 503
          ? 'API отвечает, но база данных недоступна'
          : 'API недоступен'
        : health.data.status === 'ok'
          ? 'API работает'
          : 'API отвечает, но база данных недоступна';

  return (
    <p className="data-source" role="status">
      {status}. {dataMode === 'live' ? 'Все данные — из API.' : `Из API: ${live}; остальное — тестовые данные.`}
    </p>
  );
}
