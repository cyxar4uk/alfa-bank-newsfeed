import type { AgentStep, JobStatus } from '../api/types';

/** Шаги разбора: живые из API (steps), иначе — пройденные этапы и текущий. */
export function stepsOf(job: JobStatus | null): AgentStep[] {
  if (!job) return [{ title: 'Запрашиваю разбор', state: 'running' }];
  if (job.steps?.length) return job.steps;
  const done: AgentStep[] = job.stages_done.map((t) => ({ title: t, state: 'done' }));
  if (job.status === 'queued')
    return [
      ...done,
      {
        title: job.queue_position && job.queue_position > 1 ? `Жду очереди: передо мной ${job.queue_position - 1}` : 'Жду очереди',
        detail: 'Разборы собираются по очереди, чтобы не превысить дневной лимит модели. Начну, как только освободится место.',
        state: 'running',
      },
    ];
  return job.stage ? [...done, { title: job.stage, state: 'running' }] : done;
}

/** «Шаг 7 из 12» — когда API знает план разбора; иначе только номер шага и сколько идёт разбор. */
export function progressOf(
  steps: AgentStep[],
  total: number | null | undefined,
  elapsed: number | null | undefined,
  queued = false,
): string {
  if (queued) return 'В очереди — разбор ещё не начался';
  const done = steps.filter((s) => s.state === 'done').length;
  const now = Math.min(done + 1, Math.max(steps.length, 1));
  const step = total && total >= now ? `Шаг ${now} из ${total}` : `Шаг ${now}`;
  const time = elapsed && elapsed >= 5 ? ` · идёт ${Math.round(elapsed)} с` : '';
  return step + time;
}
