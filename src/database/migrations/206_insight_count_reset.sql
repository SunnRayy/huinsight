-- V206: reset inflated insight recurrence counts (2026-11-09, docs/api-specs/insight-reinforcement.md).
-- The 165x / 108x counts came from the old extraction re-counting the same reports.
-- The true count is the number of distinct reviews that created or repeated the insight:
-- the row's own report plus the reports of deprecated rows with the same title and category
-- (the old contribution markers). Old values are kept here so the reset can be reversed.
CREATE TABLE IF NOT EXISTS ai_insight_count_resets (
    insight_id INTEGER NOT NULL,
    old_recurrence_count INTEGER NOT NULL,
    new_recurrence_count INTEGER NOT NULL,
    reset_at TIMESTAMP NOT NULL
);
INSERT INTO ai_insight_count_resets
SELECT id, recurrence_count, reviews, CURRENT_TIMESTAMP
FROM (
    SELECT a.id, a.recurrence_count,
           GREATEST(1, (SELECT COUNT(DISTINCT x.source_report_id) FROM ai_insights x
                        WHERE x.title = a.title AND x.category = a.category
                          AND (x.id = a.id OR x.status = 'deprecated')
                          AND x.source_report_id IS NOT NULL)) AS reviews
    FROM ai_insights a
    WHERE a.status <> 'deprecated'
) t
WHERE recurrence_count > reviews;
UPDATE ai_insights SET recurrence_count = r.new_recurrence_count, updated_at = CURRENT_TIMESTAMP
FROM ai_insight_count_resets r
WHERE ai_insights.id = r.insight_id AND ai_insights.recurrence_count = r.old_recurrence_count;
