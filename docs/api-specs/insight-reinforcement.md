# Insight reinforcement

Status: spec 2026-11-09, approved by the owner the same day ("three reinforcing reviews count as three
validated cases"). Router: `src/api/routes/ai_advisor.py` (`/ai-advisor`, unprefixed and under
`/api`). UI: AI Advisor → Insight Library (`components/ai-advisor/InsightManager.tsx`,
`SimilarInsightsPanel.tsx`). Code: `src/services/ai_advisor/insight_reinforcement.py` (prompt
block, links, cases) and `insight_merge.py` (groups, merging).

## Problem

A lesson counted as "repeated" only when a later review wrote the same first 80 characters in
the same category. Models never repeat wording, so in six reviews only three legacy slogans ever
matched (their 165×/108× counts are left over from the old inflation bug). Nothing raises
confidence (always 30%) and validated cases come only from manual "+ add case", so the promote
gate (confidence ≥ 70% or validated cases ≥ 3) was unreachable. The review model saw only the
validated/principle insights, so it re-invented rules. No insight carried assets
(`entity_refs`), so the radar's Decision Speed could never be measured.

## Rules

1. **Reinforcement.** A review lists the active library (id + title). Each lesson, improvement
   and rule suggestion either reinforces existing insight ids or is new. A reinforcing review
   adds, per insight, once per review: `recurrence_count + 1`, `validated_cases + 1`, and a
   `validated_case_links` entry `{source: "review", report_id, link, note, added_at}`.
   The review that created an insight is not one of its cases. Three reinforcing reviews =
   three validated cases = promotable. Promotion stays the owner's click.
2. `raw` becomes `recurring` when `recurrence_count` reaches 2 (unchanged rule). The case that
   did it carries `raised_status: true`.
3. A same-title match from a different review is a reinforcement too (same bookkeeping).
4. A reinforcement names only ids that exist and are not deprecated; unknown ids are ignored
   and the item is created as new instead.
5. Assets named by an item are resolved to canonical asset ids and merged into `entity_refs`:
   exact id or display name; a ticker or fund code matches ids ending in `_<code>`
   (`SGOV` → `US_STK_SGOV`, `110020` → `CN_FUND_110020`); "Name (TICKER)" tries both parts.
6. Deleting a review removes its raw insights (unchanged) and reverses its reinforcements:
   the case entries with that `report_id` are removed and both counters decrease. When that
   review had raised the status and no other review keeps the count at 2, it returns to `raw`.
7. **Merging a group** (owner-approved): each member is deprecated into the primary. Each
   review behind a member (its own report and its review cases) that the primary has no case
   for yet adds one validated case (`source: "merge"`); the owner's manual cases carry over.
   `recurrence_count` grows by the number of new reviews. Tags/assets are unioned. Members from
   the same review as the primary add no case: one review restating itself is not recurrence.
   The kept insight takes the group's combined wording (model-proposed, owner-editable); its
   earlier wording and every member go into `merged_from` (V207), shown as "Merged from N".
8. Migration V206 resets `recurrence_count` to the number of distinct reviews that actually
   contributed (created or matched) where the stored count is larger; old values are kept in
   `ai_insight_count_resets` so the change can be reversed.

## Section A: API Contract

### A1. Review generation (existing endpoints, additive)

The review prompt gains an "Insight library" block (active insights, at most 60: validated and
principle first, then recurring, then newest raw; `#id [status] title`). The JSON schema's
`lessons`, `improvements` and `suggestions` items become objects:

```json
{"text": "Keep 70% of SGOV as the SPX 6300 reserve; DCA may use only the rest.",
 "reinforces": [9], "assets": ["US_ETF_SGOV"]}
```

Stored `content_json` keeps those three lists as plain strings (the review page and markdown
are unchanged) and adds:

```json
"insight_links": [
  {"section": "rule_updates", "list": "suggestions", "index": 0,
   "text": "Keep 70% of SGOV as the SPX 6300 reserve; DCA may use only the rest.",
   "category": "strategy", "reinforces": [9], "assets": ["US_ETF_SGOV"]}
]
```

Plain-string items (older reviews, or a model that ignores the format) are still accepted.

### A2. `GET /ai-advisor/insights` (existing, changed default)

`limit` defaults to 200 (was 50, which hid insights). Response items unchanged:
`validated_case_links` now also holds `source: "review" | "merge"` entries.

### A3. `POST /ai-advisor/insights/similar-groups` (new)

Asks the configured model to group active insights that state the same idea. Read-only: nothing
is merged. Body: none.

```ts
interface SimilarGroupsResponse {
  groups: SimilarGroup[];
  considered: number;          // active insights sent to the model
  model_used: string;
}
interface SimilarGroup {
  theme: string;               // short label, in the insights' language
  merged_title: string;        // the group's rule in one sentence (model); kept wording if none
  primary_id: number;          // kept insight: principle > validated > recurring > oldest raw
  members: SimilarMember[];    // includes the primary first
  cases_after_merge: number;   // primary's validated_cases if this group is merged
  promotable_after_merge: boolean;
}
interface SimilarMember {
  id: number; title: string; status: 'raw'|'recurring'|'validated'|'principle';
  category: 'process'|'strategy'; source_report_id: number | null;
  report_date: string | null;  // YYYY-MM-DD of the source review, null if deleted
}
```

```json
{"considered": 52, "model_used": "gemini-3.1-pro",
 "groups": [{"theme": "SGOV 抄底储备（SPX 6300）",
   "primary_id": 9, "cases_after_merge": 3, "promotable_after_merge": true,
   "members": [
     {"id": 9, "title": "分级抄底纪律：将SPX 6300点设为‘绝望底线’…", "status": "principle", "category": "strategy", "source_report_id": 19, "report_date": "2026-04-03"},
     {"id": 21, "title": "【优化】分级抄底纪律：…", "status": "recurring", "category": "strategy", "source_report_id": 28, "report_date": "2026-05-04"},
     {"id": 44, "title": "物理隔离资金池：…", "status": "raw", "category": "process", "source_report_id": 57, "report_date": "2026-08-09"},
     {"id": 55, "title": "Ring-Fence Emergency SGOV Reserves: …", "status": "raw", "category": "process", "source_report_id": 72, "report_date": "2026-11-08"}]}]}
```

Groups have at least two members; an insight appears in at most one group; ids the model
invents are dropped. The model is told that a later refinement or amendment of a rule belongs
with that rule, and that sharing a topic is not enough. Errors: 502 `{"error": {"code": "ERR_INSIGHT_GROUPS_LLM", "message"}}`
when the model call fails or returns no parsable groups.

### A4. `POST /ai-advisor/insights/{primary_id}/merge-group` (new)

Body `{"member_ids": [21, 44, 55], "title": "combined wording (optional, ≤ 500)"}` (primary excluded).
List items gain `merged_from` (JSON text: `[{id, title, report_id, merged_at, replaced_wording?}]`). Applies rule 7 in one transaction and
returns the primary in the `GET /insights` item shape plus `cases_added: int`. 404 when the
primary is missing; 422 when a member is the primary, missing, or already deprecated.

### A5. `DELETE /ai-advisor/review/{id}` (existing, additive)

Also reverses that review's reinforcements (rule 6).

## Section B: Data Binding Map

| UI element | Field | Format |
|---|---|---|
| "Find similar insights" button | POST A3 | ChipBtn `join_inner`; spinner while running |
| Group card title | `theme` | text as returned |
| Combined rule | `merged_title` | FormTextarea, editable; sent as `title` |
| Member row | `title`, `report_date`, `status` | title (one line, ellipsis) · mono date · status Pill |
| Kept marker | `primary_id` | primary Pill "Kept" / "保留" |
| Outcome line | `cases_after_merge`, `promotable_after_merge` | "{n} validated cases after merging · promotable" |
| Member checkbox | client only (default ticked) | unticked members stay as they are |
| Outcome when some are unticked | `cases_after_merge` | "{n} validated cases if all are merged", no Promotable pill |
| Merge button | POST A4 with the ticked member ids | ActionBtn primary `merge`; disabled at 0 |
| Skip | client only | ChipBtn, hides the group |
| Existing library row | `validated_cases`, `recurrence_count` | unchanged |

### Library row (2026-11-09 revision, after the owner's review)

| Element | Field | Rule |
|---|---|---|
| "Seen in N reviews" | `recurrence_count` | always |
| ●●○ "2 of 3 cases" / "Ready to promote" | `validated_cases` | hidden on Principle |
| "Promote to {next}" | `promote_eligible`, `status` | shown only when eligible |
| "Use as" select | `rule_layer` | only on Validated / Principle |
| "Merged from N ▾" | `merged_from` | only when non-empty |

Confidence (always 30%, nothing updates it) and the per-row unmet-gate line are no longer shown;
one line under the header explains how cases accrue.

## Section C: Demo Data Markers

None: the panel shows only model-proposed groups of real rows. Static strings: button labels,
"Kept", the outcome line.

## Section D: Component Reference

```
Insight Library  52                     [All Statuses ▾] [All Categories ▾] [⊕ Find similar insights]
┌ Similar insights · 5 groups ───────────────────────────────────────────────┐
│ SGOV 抄底储备（SPX 6300）                    3 validated cases after merging · promotable │
│  KEPT  分级抄底纪律：将SPX 6300点…          2026-04-03  PRINCIPLE          │
│  [✓]   【优化】分级抄底纪律：…              2026-05-04  RECURRING          │
│  [✓]   物理隔离资金池：…                    2026-08-09  RAW                │
│                                       [Skip]  [⇄ Merge 3 into the kept one] │
└────────────────────────────────────────────────────────────────────────────┘
```

Built from the operations kit (Card, CardHeader, Pill, ActionBtn, ChipBtn, Notice). Result of a
merge: success Notice "Merged 3 into #9 · 3 validated cases"; error Notice with the server reason.

## Section E: Data Quality Requirements

- UI strings in en and zh-CN (`aiAdvisor` namespace); 中文 uses 用户 where a person is meant.
- Insight titles are shown as stored (either language). Dates `YYYY-MM-DD` mono.
- No currency or percentages in this feature except the existing confidence display.

## Validation Checklist

- [x] Backend: reinforcement, same-title match, unknown ids, idempotent re-extraction, delete
      reversal, merge-group, migration V206 (`tests/services/ai_advisor/test_insight_reinforcement.py`).
- [x] Prompt: library block present in both languages; schema documents `reinforces`/`assets`.
- [x] Frontend: panel states (loading, groups, empty, error, merged, refused, unticked) en + zh
      (`ux-command-center/tests/similar-insights.test.tsx`).
- [x] Local run on the production mirror (2026-11-09): V206 reset 165/165/108 → 2/2/2; all 52
      insights listed (was capped at 50); similar-groups (gemini-3.5-flash, 32 s) proposed 7 groups,
      the SGOV/SPX 6300 theme spanning 4 reviews with 3 cases after merging. Two test reviews
      (Aug–Oct) linked 5 of 7 and 7 of 7 items to existing ids, one link loose (order-cleanup SOP →
      value-bucket rule); both deleted again, library back to its starting state.

Known limit: the model judges what counts as "the same rule", and an occasional loose link adds
a case. Promotion stays the owner's click, so a loose case cannot promote anything by itself.
