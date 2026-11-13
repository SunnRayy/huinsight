# Returns owner actions

Status: implemented 2026-11-09 (P&L audit follow-up). Router: `src/api/routes/returns_owner.py`,
mounted unprefixed (local) and under `/api` (Cloud Run). UI: the Data Sources page,
"Investment returns: missing data and corrections" (`components/settings/ReturnsInputs.tsx`,
anchor `#returns-inputs`). Performance → Returns only reports, with a banner linking there
when something is waiting.

`GET /performance/returns-inputs` gives the card's state:
`{"coverage": <coverage_status>, "corrections": int|null}`. `corrections` counts the
locked-month records that the uploaded funding workbook would change. It is cached per
workbook file (mtime, size) and per frozen-flows pin, since reading the workbook takes about 0.6 s.

Every write appends a `sync_metrics_log` row (`trigger` names the action, `note` is JSON) and
re-derives coverage with `extend_flow_coverage`.

## Re-review the frozen history

The flows up to `frozen_coverage_end` are immutable to the sync. After the owner corrects them
in the funding workbook (`TWR外部现金流`) and syncs, these endpoints replace them.

`GET /performance/twr-rereview` (read-only)

```json
{"available": true, "frozen_end": "2026-08-31", "workbook": "funding_transactions.xlsx",
 "workbook_sha256": "…", "changes": [{"flow_id": "…", "change": "changed",
 "fields": ["amount_cny", "original_amount", "evidence_status"], "event_date": "2026-03-15",
 "source": "RSU", "before_cny": 0.0, "after_cny": 0.0, "before_native": 0.0, "after_native": 0.0,
 "before_status": "…", "after_status": "…"}], "evidence_text_changes": 0, "net_change_cny": 0.0,
 "history_changed_since_review": true, "needs_review": true}
```

`available: false` carries `reason`: `no_frozen_history` | `workbook_missing` | `twr_tabs_missing`.
A change is economic (date, CNY and native amount to the cent, currency, FX, source, kind,
evidence status). Evidence or date-basis text alone is counted in `evidence_text_changes`.

`POST /performance/twr-rereview` with body `{"reviewer": str(1..100), "evidence_ref": str(1..500)}`.
In one transaction, it archives the stored non-automatic rows on or before the frozen end to
`investment_external_flows_archive` and writes the workbook rows. It then re-pins
`frozen_flows_sha256`, `frozen_valuation_sha256` and `valuation_identity_sha256` and clears
`history_changed_since_review`. After that it re-derives later months, records
`investment_twr_reviews` for the new input fingerprint, and logs `trigger = twr_rereview`.

```json
{"status": "ok", "archived_rows": 0, "written_rows": 0, "changes": [], "coverage": {},
 "input_fingerprint": "…", "sync_log_id": 1}
```

The request is refused with 422 `{"error": {"code": "ERR_TWR_REREVIEW_REFUSED", "message": …}}`
when the history is not frozen yet, a field is blank, or the workbook is invalid.

## TTFund coverage

The CN gate passes a month once TTFund activity is known through its end. The web-list paste
proves activity only up to its last event, so a month with no trades needs a coverage record
(`cn_platform_coverage`, V205). A record counts only if it joins the evidence before it, with no gap.

`POST /performance/ttfund-cli-import` (multipart `file`, ≤ 5 MB): a
`huinsight.ttfund_cli_pull.v1` JSON from `scripts/ttfund_pull.py`, which runs the read-only
`ttskill invoke TRADE_QUERY --action trade_list` for `tradeType` `all` (required) and `hqb`.
Trades dated after the last web-list event become `cn_platform_events`. The queried range is
recorded with `basis = cli_pull` (sourced). Logged as `trigger = ttfund_cli_import`.

```json
{"coverage_id": 1, "covered_from": "2026-09-12", "covered_to": "2026-11-09", "trades_in_range": 0,
 "already_in_web_list": 0, "imported_events": 0, "coverage": {}, "sync_log_id": 2}
```

`POST /performance/ttfund-attestation` with body
`{"covered_from": date, "covered_to": date, "note": str(1..500)}`. The fallback when no pull is
possible: `basis = owner_attestation` (attested, no events). `covered_to` must be before today.
Logged as `trigger = ttfund_attestation`.

Both return 422 `ERR_TTFUND_*_REFUSED` with the reason for an invalid export or attestation.

## Additive fields elsewhere

- `GET /performance/returns` → `locked_history_corrections` (same count as above). The
  Returns tab shows its Data Sources banner when this is > 0 or when TTFund months block.
- `GET /performance/returns` → `coverage_status.cn_coverage = {"through": date|null, "records":
  [{"from", "to", "basis": "cli_pull"|"owner_attestation", "recorded_at"}]}`. The Returns tab
  shows a chip per record: sourced or attested.
- `GET /performance/summary` → `fx_effect_cny` (all-time only, else null). This is the lifetime
  bridge's FX line, `usd_flow_fx_effect`: Returns flows at their dated rate minus the same
  flows at today's rate.
- `GET /performance/gains` → `xirr_under_one_year` (bool). The first money in is under 365 days
  before the valuation day. The XIRR is still annualized, and the UI tags it "持有期不足一年".
