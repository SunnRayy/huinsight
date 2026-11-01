# ADR-029: One Provider per Valuation Series (CN Broad Indexes from CSIndex)

**Date:** 2026-10-23
**Status:** Accepted
**Deciders:** Ray (Owner), Claude Code (Lead)

---

## Context

The Valuation page ranks today's PE for 沪深300, 中证500 and 上证50 against 10 years of history
(`valuation_history`). Both came from legulegu (`akshare.stock_index_pe_lg`).

On Cloud Run that fetch failed on every refresh from 2026-09-19 onward: the page arrived without
its `_csrf` meta tag. The page went on showing the 09-19 values as if they were current, and the
refresh summary reported "0 errors". The same URL answers from Cloud Shell, so the cause is
probably a block on Cloud Run's outbound IPs (unverified).

CSIndex, the index provider itself (`akshare.stock_zh_index_hist_csindex`), answers from Google
Cloud and returns about 11 years of daily 滚动市盈率 in one request.

The two providers disagree. CSIndex's TTM PE ran about 5% above legulegu's on the same day (12.62
vs 12.06 for 沪深300 on 2026-10-22). The CSIndex 市盈率2 snapshot series was 17–31% higher still.
Ranking one provider's value against the other's history would bias the percentile, and with it
the signal: the "two sources for one number" failure class.

---

## Decision

**A valuation percentile is computed within a single provider's series.**

The three CN broad indexes (`_CSINDEX_INDEXES` in `src/services/valuation/collector.py`) take
both today's PE and the history from CSIndex (`fetch_cn_index_csindex`).

- `_replace_series` writes the CSIndex series with `ON CONFLICT ... DO UPDATE`, so a date that
  legulegu already filled holds the CSIndex value.
- `_get_history_percentile(..., source="csindex")` ranks against CSIndex rows only. Legulegu rows
  on dates CSIndex lacks stay stored but are not ranked.
- PB has no CSIndex equivalent and stays best-effort from legulegu (`fetch_cn_index_pb`). It shows
  "—" where legulegu does not answer; no other provider's PB is substituted.

A tracked index that returns no data is counted as a failure in the refresh summary. The API
flags its row `is_stale`, and the page shows "Not updated · as of DATE" rather than passing the
old value off as today's.

---

## Consequences

**Positive:**
- CN index valuation works again on cloud. Value and history come from the authoritative provider.
- The percentile can't be biased by a provider mismatch.
- Failures are visible: refresh-summary errors and as-of dates.

**Negative / Trade-offs:**
- The signal basis changed at the switch. 沪深300 went from the 63rd percentile (legulegu, 09-19)
  to the 35th (CSIndex, 10-22). That reflects the provider's definition, not a market move.
- PB for these indexes is unavailable on cloud for as long as legulegu stays unreachable.
- Adding another provider for an existing ticker/metric later requires either a full series
  replacement or a source-scoped percentile, never a fallback mix.

---

## Related
- CHANGELOG 0.1.23.
- Memory `two-sources-signature-bug`.
- Tests: `tests/services/valuation/test_collector.py::TestCsindexTrackedIndex`.
