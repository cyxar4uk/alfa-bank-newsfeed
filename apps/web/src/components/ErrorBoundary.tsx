import { Component, type ReactNode } from 'react';
import { ErrorState } from './States';

/** Ошибка рендера одного экрана (например, неожиданный ответ API) не роняет весь интерфейс. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          title="Не удалось показать экран"
          error={new Error('Сервер вернул данные в неожиданном виде')}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
