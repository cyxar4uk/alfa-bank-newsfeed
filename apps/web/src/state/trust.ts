// Доверие к выводу: готов ли разбор заранее, сколько утверждений подтверждено и чем, где прогноз банка разошёлся
// с фактом. Все поля API необязательные: нет их — ничего не показываем, экран как раньше.
import type { Claim, FeedItem, Insight, RiskMap } from '../api/types.ts';
import { plural } from './screens.ts';

export type Readiness = 'ready' | 'queued';

/** Готов ли разбор: insight_state из API, иначе прежний insight_ready; «none» и неизвестное — без отметки. */
export function readinessOf(item: Pick<FeedItem, 'insight_state' | 'insight_ready'>): Readiness | null {
  if (item.insight_state === 'ready' || item.insight_state === 'queued') return item.insight_state;
  if (item.insight_state == null && item.insight_ready === true) return 'ready';
  return null;
}

export const SUPPORT_LABEL: Record<NonNullable<Claim['support']>[number]['kind'], string> = {
  news: 'Новость',
  bank: 'Альфа-Банк',
  data: 'Данные компании',
};

export interface ClaimRow {
  text: string;
  status: Claim['status'];
  support: { kind: keyof typeof SUPPORT_LABEL; label: string }[];
}

export interface ClaimsView {
  verified: number;
  total: number;
  /** «12 из 12 утверждений подтверждены» */
  label: string;
  /** все подтверждены — зелёная отметка; иначе нейтральная */
  allVerified: boolean;
  rows: ClaimRow[];
}

/** «Поставщики …» → «поставщики …», но «ЦБ …» остаётся «ЦБ …»: аббревиатуры не трогаем. */
function lowerFirst(text: string): string {
  return /^.[а-яёa-z]/.test(text) ? text[0].toLowerCase() + text.slice(1) : text;
}

/** Сводка проверки утверждений; null — агент её не прислал. */
export function claimsOf(insight: Pick<Insight, 'claims' | 'verified_count' | 'claims_total'>): ClaimsView | null {
  const claims = (insight.claims ?? []).filter((c) => c && c.text);
  if (claims.length === 0) return null;
  const total = insight.claims_total ?? claims.length;
  if (total <= 0) return null;
  const verified = Math.min(insight.verified_count ?? claims.filter((c) => c.status === 'verified').length, total);
  const verb = verified === 0 ? 'подтверждено' : plural(verified, ['подтверждено', 'подтверждены', 'подтверждены']);
  return {
    verified,
    total,
    label: `${verified} из ${total} ${plural(total, ['утверждения', 'утверждений', 'утверждений'])} ${verb}`,
    // «всё подтверждено» — только если и счёт, и сам список это говорят
    allVerified: verified >= total && claims.every((c) => c.status === 'verified'),
    rows: claims.map((c) => ({
      // Предположение подаём как предположение: «Возможно, …»
      text: c.status === 'hypothesis' && !/^возможно/i.test(c.text) ? `Возможно, ${lowerFirst(c.text)}` : c.text,
      status: c.status,
      support: (c.support ?? [])
        .filter((s) => s && s.kind in SUPPORT_LABEL)
        .map((s) => ({ kind: s.kind, label: s.label || SUPPORT_LABEL[s.kind] }))
        // один источник — одна подпись: два признака компании не дают «Данные компании, Данные компании»
        .filter((s, i, all) => all.findIndex((x) => x.kind === s.kind && x.label === s.label) === i),
    })),
  };
}

export interface OutdatedSignal {
  /** «Курс рубля» */
  topic: string;
  /** «Банк ждёт 87 ₽/$, сейчас 80,6» */
  text: string;
}

/** Где прогноз банка разошёлся с фактом: факторы карты и позиция банка в разборе главного события. */
export function outdatedSignals(map: RiskMap | null, lead: Insight | null): OutdatedSignal[] {
  const out: OutdatedSignal[] = [];
  for (const f of map?.factors ?? []) {
    if (f.bank?.outdated) out.push({ topic: f.label, text: f.bank.outdated_note || `${f.bank.text} — прогноз устарел` });
  }
  const bp = lead?.bank_position;
  if (bp?.outdated) {
    const text = bp.outdated_note || `${bp.statement} — прогноз устарел`;
    if (!out.some((o) => o.text === text)) out.push({ topic: lead?.event.title ?? 'Главное событие', text });
  }
  return out.slice(0, 3);
}
