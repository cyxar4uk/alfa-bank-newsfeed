import { useEffect, useState } from 'react';

// План работы агента. API пока не отдаёт шаги по ходу работы, поэтому подсвечиваем их по времени и не
// отмечаем выполненными: точный ход работы будет в трассе разбора.
const STEPS = [
  'Профиль компании и связи с контрагентами',
  'Новости по событию',
  'Материалы аналитиков Альфа-Банка',
  'Сопоставление события с признаками компании',
  'Проверка, что у каждого вывода есть источник',
];

const STEP_MS = 700;

export function AnalysisSteps() {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setCurrent((n) => Math.min(n + 1, STEPS.length - 1)), STEP_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="analysis" aria-labelledby="analysis-title">
      <h2 className="analysis__title" id="analysis-title">
        Готовим разбор для вашей компании
      </h2>
      <p className="analysis__lead" role="status">
        Обычно это занимает до 30 секунд. Агент проходит шаги по плану:
      </p>
      <ol className="analysis__steps">
        {STEPS.map((step, i) => (
          <li key={step} className={`analysis__step ${i === current ? 'is-active' : ''}`}>
            <span className="analysis__mark" aria-hidden="true">
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>
    </section>
  );
}
