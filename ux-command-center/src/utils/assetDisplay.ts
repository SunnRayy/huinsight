/**
 * assetDisplay — turn internal asset ids (US_STK_BRK-B, RSU_AMZN, ALTS_Paper_Gold)
 * into what a person reads: a ticker or name, plus a short market badge.
 *
 * Display only. The id stays the key everywhere else; this never feeds a
 * calculation or a lookup.
 */

/** Id prefix → short badge shown in list rows. Longest prefixes first. */
const BADGES: Array<[string, string]> = [
  ['US_STK_', 'US'],
  ['US_ETF_', 'US'],
  ['CN_FUND_', 'CN'],
  ['CN_STK_', 'CN'],
  ['HK_', 'HK'],
  ['RSU_', 'RSU'],
  ['ALTS_', 'ALT'],
  ['CASH_', 'CASH'],
  ['INS_', 'INS'],
  ['Bond_', 'BOND'],
  ['Pension_', 'PEN'],
  ['Property_', 'PROP'],
  ['Wealth_', 'WLTH'],
];

/** The id with its market/type prefix removed, or the id when no prefix matches. */
function stripPrefix(id: string): string {
  for (const [prefix] of BADGES) {
    if (id.startsWith(prefix)) return id.slice(prefix.length);
  }
  return id;
}

/**
 * Human-readable asset name. A real name from the API wins; when the API only
 * echoes the id back (US stocks have no registry name), fall back to the ticker.
 */
export function displayAssetName(id: string, name?: string | null): string {
  if (name && name.trim() && name !== id) return name;
  if (id.startsWith('RSU_')) return `${stripPrefix(id)} RSU`;
  if (id.startsWith('US_') || id.startsWith('CN_') || id.startsWith('HK_')) return stripPrefix(id);
  return stripPrefix(id).replace(/_/g, ' ');
}

/** Short market/type badge for an asset id, e.g. "US", "CN", "RSU". */
export function assetBadge(id: string): string {
  for (const [prefix, badge] of BADGES) {
    if (id.startsWith(prefix)) return badge;
  }
  return id.slice(0, 3).toUpperCase();
}

/**
 * Row title for asset tables. US listings read best as their ticker (QQQ, VOO);
 * the registry's broker names are uppercase legal names ("INVSC QQQ TRUST SRS 1
 * ETF"). Everything else uses displayAssetName.
 */
export function assetTitle(id: string, name?: string | null): string {
  if (id.startsWith('US_STK_') || id.startsWith('US_ETF_')) return stripPrefix(id);
  return displayAssetName(id, name);
}
