import { api, ApiError } from '../api/client';
import { useAsync } from '../state/useAsync';

/** Жив ли API: данные на экранах сервиса — только из него. */
export function DataSource() {
  const health = useAsync((signal) => api.health(signal), 'health');
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
      {status}
    </p>
  );
}
