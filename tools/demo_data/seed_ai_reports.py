"""Phase 3b: Sample report seeding (brief/review with demo-sample marker).

These functions are called by seed_ai.py's seed_all() to write ONE sample daily
Brief and ONE sample completed Review to ai_reports with model_used =
'demo-sample'. The frontend uses this marker to badge the rows as samples.
"""
from __future__ import annotations

import json
from typing import Any

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.section_ids import (
    BRIEF_SECTION_IDS,
    DEFAULT_LANGUAGE,
    REVIEW_SECTION_IDS,
    section_label,
)

# model_used marker written to the Phase 3b sample brief/review rows in
# ai_reports. A real generated report always carries the LLM's own
# model_used string (e.g. "gemini/gemini-2.5-flash"), so this value can never
# collide with one — it both identifies "the demo-sample row for this
# report_type" (this script's idempotency key) AND is
# what the frontend badge checks for to label the content as a sample rather
# than a real AI output.
DEMO_SAMPLE_MODEL_MARKER = "demo-sample"


def _render_sample_markdown(
    section_ids: list[str], content_json: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> str:
    """Minimal, deterministic markdown rendering of a sample report's
    content_json — good enough for the UI's "copy markdown" convenience
    action. Headings use the same display-label resolver
    (section_label) the real generators use, so a sample report's markdown
    heading matches what a real one of the same language would show.
    """
    lines: list[str] = []
    for key in section_ids:
        section = content_json.get(key)
        if not isinstance(section, dict):
            continue
        lines.append(f"## {section_label(key, language)}")
        narrative = section.get("narrative")
        if narrative:
            lines.append(str(narrative))
        for field, value in section.items():
            if field == "narrative" or not isinstance(value, list) or not value:
                continue
            for item in value:
                if isinstance(item, dict):
                    summary = " · ".join(
                        f"{k}={v}" for k, v in item.items() if v not in (None, "")
                    )
                    lines.append(f"- {summary}")
                else:
                    lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _seed_sample_report(
    db: DatabaseConnector, report_type: str, sample: dict[str, Any], section_ids: list[str]
) -> None:
    """Idempotent upsert of ONE sample ai_reports row for `report_type`.

    ai_reports has no natural unique key to ON CONFLICT against (id is a bare
    sequence) — so the marker itself is the key: look up the single row for
    this report_type already carrying DEMO_SAMPLE_MODEL_MARKER, UPDATE it if
    found, INSERT a new one if not. See seed_ai.py module docstring
    "IDEMPOTENCY".
    """
    content_json = sample["content_json"]
    content_json_str = json.dumps(content_json, ensure_ascii=False)
    content_markdown = _render_sample_markdown(section_ids, content_json)
    # Deliberately minimal — this is informational only; no UI reads a
    # sample row's context_config for anything but display, and none of the
    # ContextPanel tier fields are meaningful for a row nothing generated.
    context_config_json = json.dumps({"demo_sample": True}, ensure_ascii=False)
    title = sample.get("title")
    period_start = sample.get("period_start")
    period_end = sample.get("period_end")

    existing = db.execute(
        "SELECT id FROM ai_reports WHERE report_type = ? AND model_used = ?",
        [report_type, DEMO_SAMPLE_MODEL_MARKER],
    ).fetchone()

    if existing:
        db.execute(
            """
            UPDATE ai_reports
            SET title = ?, context_config_json = ?, content_json = ?, content_markdown = ?,
                period_start = ?, period_end = ?
            WHERE id = ?
            """,
            [
                title,
                context_config_json,
                content_json_str,
                content_markdown,
                period_start,
                period_end,
                existing[0],
            ],
        )
    else:
        db.execute(
            """
            INSERT INTO ai_reports (
                report_type, title, context_config_json, content_json, content_markdown,
                model_used, period_start, period_end
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                report_type,
                title,
                context_config_json,
                content_json_str,
                content_markdown,
                DEMO_SAMPLE_MODEL_MARKER,
                period_start,
                period_end,
            ],
        )


def seed_sample_reports(db: DatabaseConnector, seed: dict[str, Any]) -> None:
    _seed_sample_report(db, "brief", seed["sample_brief"], BRIEF_SECTION_IDS)
    _seed_sample_report(db, "review", seed["sample_review"], REVIEW_SECTION_IDS)
