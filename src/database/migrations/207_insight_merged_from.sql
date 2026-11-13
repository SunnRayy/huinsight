-- V207: what was merged into an insight (2026-11-09, docs/api-specs/insight-reinforcement.md A4).
-- [{id, title, report_id, merged_at}] for each insight folded in by merge-group, plus the kept
-- insight's own earlier wording when the merge replaced it. Shown as "Merged from N".
ALTER TABLE ai_insights ADD COLUMN IF NOT EXISTS merged_from JSON;
