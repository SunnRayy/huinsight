import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, LifetimeBridgeResponse } from '../../src/services/api';
import { useFormatCurrencyStr } from '../../src/utils/format';

/** Audit 2026-11-08 issue 6: Overview lifetime P&L reconciled to the Returns
 *  investment gain, line by line. Loaded on first open — it takes a few seconds. */
export const LifetimeBridge: React.FC<{ includeNonRebalanceable: boolean }> = ({ includeNonRebalanceable }) => {
   const { t } = useTranslation('performance');
   const money = useFormatCurrencyStr();
   const [bridge, setBridge] = useState<LifetimeBridgeResponse | null>(null);
   const [error, setError] = useState<string | null>(null);
   const [loadedFor, setLoadedFor] = useState<boolean | null>(null);

   const load = () => {
      if (loadedFor === includeNonRebalanceable) return;
      setLoadedFor(includeNonRebalanceable);
      setBridge(null);
      setError(null);
      api.getLifetimeBridge(includeNonRebalanceable).then(setBridge).catch((e: Error) => setError(e.message));
   };
   const params = bridge
      ? { start: bridge.period_start, end: bridge.as_of, last: bridge.last_month_end, today: bridge.today }
      : {};

   return (
      <details
         id="lifetime-bridge"
         className="mb-6 text-xs text-slate-600 dark:text-slate-300 scroll-mt-6"
         data-testid="lifetime-bridge"
         onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) load(); }}
      >
         <summary className="cursor-pointer text-right text-slate-400 hover:text-slate-600">{t('overview.bridge.toggle')}</summary>
         <div className="mt-2 rounded-lg border border-slate-200 dark:border-border-dark p-3">
            {error && <p className="text-red-500">{error}</p>}
            {!error && !bridge && <p>{t('overview.bridge.loading')}</p>}
            {bridge && !bridge.available && <p>{t('overview.bridge.unavailable', { reason: bridge.reason })}</p>}
            {bridge?.available && (
               <>
                  <table className="w-full">
                     <tbody>
                        {bridge.lines?.filter((l) => l.key === 'returns_gain' || Math.abs(l.amount_cny) >= 1).map((l) => (
                           <tr key={l.key}>
                              <td className="py-0.5">{t(`overview.bridge.lines.${l.key}`, params)}</td>
                              <td className="py-0.5 text-right tabular-nums">{money(l.amount_cny)}</td>
                           </tr>
                        ))}
                        <tr className="border-t border-slate-200 dark:border-border-dark font-semibold">
                           <td className="py-0.5">{t('overview.bridge.overview')}</td>
                           <td className="py-0.5 text-right tabular-nums">{money(bridge.overview_lifetime_cny ?? 0)}</td>
                        </tr>
                     </tbody>
                  </table>
                  {bridge.by_source?.filter((s) => s.items).map((s) => (
                     <div key={s.group} className="mt-2" data-testid={`bridge-source-${s.group}`}>
                        <p className="font-medium">{t('overview.bridge.sourceRemainder', { source: s.label, amount: money(s.remainder_cny) })}</p>
                        <ul className="ml-4 list-disc">
                           {s.items!.filter((i) => i.kind === 'timing' || Math.abs(i.amount_cny) >= 1).map((i, n) => (
                              <li key={n}>
                                 {t(`overview.bridge.items.${i.kind}`, { month: i.month })}
                                 {i.kind !== 'timing' && <span className="tabular-nums">: {money(i.amount_cny)}</span>}
                              </li>
                           ))}
                        </ul>
                     </div>
                  ))}
                  <p className={`mt-2 ${bridge.within_threshold ? 'text-emerald-600' : 'text-amber-600'}`}>
                     {t(bridge.within_threshold ? 'overview.bridge.unexplainedOk' : 'overview.bridge.unexplainedHigh', {
                        amount: money(bridge.unexplained_cny ?? 0), threshold: money(bridge.threshold_cny ?? 5000),
                     })}
                  </p>
               </>
            )}
         </div>
      </details>
   );
};
