import type { IconName } from './Icon';

/** Иконка фактора по коду из каталога (rate, fx, demand_56, commodity_oil…). */
export function factorIcon(code: string): IconName {
  if (code === 'rate') return 'rate';
  if (code === 'deposit_yield') return 'deposit';
  if (code === 'fx') return 'fx';
  if (code === 'ved_logistics') return 'ved';
  if (code === 'consumer') return 'consumer';
  if (code === 'labor') return 'labor';
  if (code === 'gov') return 'gov';
  if (code === 'inflation') return 'inflation';
  if (code === 'region') return 'region';
  if (code === 'growth') return 'inflation';
  if (code === 'commodity_gold') return 'gold';
  if (code === 'supply_52') return 'logistics';
  if (code.startsWith('commodity_')) return 'oil';
  if (code.startsWith('demand_')) return 'buyers';
  if (code.startsWith('supply_')) return 'suppliers';
  return 'radar';
}
