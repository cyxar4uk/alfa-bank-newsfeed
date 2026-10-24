import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Shell, PrototypeNotice } from './components/Shell';
import { ErrorState, Skeleton } from './components/States';
import { EventPage } from './pages/EventPage';
import { AnalyzePage } from './pages/AnalyzePage';
import { BriefingPage } from './pages/BriefingPage';
import { ExposureMapPage } from './pages/ExposureMapPage';
import { HomePage } from './pages/HomePage';
import { LoginPage } from './pages/LoginPage';
import { TracePage } from './pages/TracePage';
import { WeeklyPage } from './pages/WeeklyPage';
import { SessionProvider, useDirectory, useSession } from './state/session';

function RequireUser() {
  const { persona } = useSession();
  return persona ? <Shell /> : <Navigate to="/login" replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireUser />}>
        <Route index element={<HomePage />} />
        <Route path="radar" element={<BriefingPage />} />
        <Route path="radar/map" element={<ExposureMapPage />} />
        <Route path="radar/weekly" element={<WeeklyPage />} />
        <Route path="radar/analyze" element={<AnalyzePage />} />
        <Route path="radar/trace/:traceId" element={<TracePage />} />
        <Route path="radar/:eventId" element={<EventPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  const directory = useDirectory();

  if (directory.status !== 'ok') {
    return (
      <div className="app">
        <PrototypeNotice />
        <div className="boot">
          {directory.status === 'loading' ? (
            <div className="boot__loading" aria-busy="true" aria-label="Загружаем">
              <Skeleton width={220} height={24} />
              <Skeleton width={320} />
              <Skeleton width={280} />
            </div>
          ) : (
            <ErrorState title="Не удалось загрузить тестовых пользователей" error={directory.error} onRetry={directory.retry} />
          )}
        </div>
      </div>
    );
  }

  return (
    <SessionProvider personas={directory.data.personas} companies={directory.data.companies}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </SessionProvider>
  );
}
