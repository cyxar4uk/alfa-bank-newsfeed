import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// В разработке /api проксируется на локальный API: у API нет CORS, а с прокси запросы идут с того же адреса.
// Собрать с VITE_API_URL=/ — интерфейс ходит в API через этот прокси (или через nginx в образе).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
    preview: { proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
  };
});
