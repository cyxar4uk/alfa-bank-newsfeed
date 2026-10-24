import type { AgentStep, JobStatus } from '../api/types';

/** Шаги разбора: живые из API (steps), иначе — пройденные этапы и текущий. */
export function stepsOf(job: JobStatus | null): AgentStep[] {
  if (!job) return [{ title: 'Запрашиваю разбор', state: 'running' }];
  if (job.steps?.length) return job.steps;
  const done: AgentStep[] = job.stages_done.map((t) => ({ title: t, state: 'done' }));
  if (job.status === 'queued')
    return [...done, { title: job.queue_position && job.queue_position > 1 ? `Жду очереди: передо мной ${job.queue_position - 1}` : 'Жду очереди', state: 'running' }];
  return job.stage ? [...done, { title: job.stage, state: 'running' }] : done;
}
