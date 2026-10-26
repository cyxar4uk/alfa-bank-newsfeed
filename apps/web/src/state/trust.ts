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
  company: 'Данные банка о компании',
};

export interface ClaimRow {
  text: string;
  status: Claim['status'];
  /** опоры: вид и текст («признак: значение», предложение новости) */
  support: { kind: keyof typeof SUPPORT_LABEL; quote: string | null }[];
  /** числа без опоры — честно показываем */
  unsupported: string[];
}

export interface ClaimsView {
  verified: number;
  total: number;
  /** «12 из 12 утверждений подтверждены», «…, предположений — 2» */
  label: string;
  /** всё подтверждено — зелёная отметка; иначе нейтральная */
  allVerified: boolean;
  rows: ClaimRow[];
}

/** «Поставщики …» → «поставщики …», но «ЦБ …» остаётся «ЦБ …»: аббревиатуры не трогаем. */
function lowerFirst(text: string): string {
  return /^.[а-яёa-z]/.test(text) ? text[0].toLowerCase() + text.slice(1) : text;
}

/** Сводка проверки утверждений; null — агент её не прислал. */
export function claimsOf(insight: Pick<Insight, 'claims' | 'claims_summary'>): ClaimsView | null {
  const claims = (insight.claims ?? []).filter((c) => c && c.text);
  const sum = insight.claims_summary ?? null;
  const total = sum?.total ?? claims.length;
  if (total <= 0) return null;
  const verified = Math.min(sum?.verified_count ?? claims.filter((c) => c.status === 'verified').length, total);
  const hypotheses = sum?.hypothesis_count ?? claims.filter((c) => c.status === 'hypothesis').length;
  const verb = verified === 0 ? 'подтверждено' : plural(verified, ['подтверждено', 'подтверждены', 'подтверждены']);
  return {
    verified,
    total,
    label:
      `${verified} из ${total} ${plural(total, ['утверждения', 'утверждений', 'утверждений'])} ${verb}` +
      (hypotheses > 0 ? `, ${plural(hypotheses, ['предположение', 'предположения', 'предположений'])} — ${hypotheses}` : ''),
    // «всё подтверждено» — только если и счёт, и сам список это говорят
    allVerified: verified >= total && claims.every((c) => c.status === 'verified'),
    rows: claims.map((c) => ({
      // Предположение подаём как предположение: «Возможно, …»
      text: c.status === 'hypothesis' && !/^возможно/i.test(c.text) ? `Возможно, ${lowerFirst(c.text)}` : c.text,
      status: c.status,
      support: (c.support ?? [])
        .filter((s) => s && s.kind in SUPPORT_LABEL)
        .map((s) => ({ kind: s.kind, quote: s.quote?.trim() || null }))
        // одна и та же опора дважды не нужна
        .filter((s, i, all) => all.findIndex((x) => x.kind === s.kind && x.quote === s.quote) === i),
      unsupported: (c.unsupported_numbers ?? []).filter(Boolean),
    })),
  };
}

/** Пояснение банка пишется со строчной («банк ждал Urals $63, в новостях — $72») — отдельной строкой с заглавной. */
export function capitalize(text: unknown): string {
  if (typeof text !== 'string') return '';
  const t = text.trim();
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

/** Подпись кнопки менеджеру: «Обсудить с менеджером: форвард на валютную выручку»; продукт уже есть — «Проверить условия: …». */
export function managerLabel(products: FeedItem['products'] | undefined): string {
  const p = (products ?? []).find((x) => x && x.name);
  if (!p) return 'Оставить заявку менеджеру';
  const name = /^.[а-яёa-z]/.test(p.name) ? p.name[0].toLowerCase() + p.name.slice(1) : p.name;
  return `${p.owned ? 'Проверить условия' : 'Обсудить с менеджером'}: ${name}`;
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
  // Разбор агента говорит только о более свежем материале банка, не о расхождении с фактом — в баннер не идёт.
  void lead;
  return out.slice(0, 3);
}
