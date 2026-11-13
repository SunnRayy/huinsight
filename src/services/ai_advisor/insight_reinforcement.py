"""Insight reinforcement: link review lessons to the insights they repeat (2026-11-09).

Spec: docs/api-specs/insight-reinforcement.md.

Before this, a lesson counted as "repeated" only when a later review wrote the same
first 80 characters; models never repeat wording, so nothing ever recurred and the
promote gate (confidence >= 70% or 3 validated cases) was unreachable. Now:

* the review prompt lists the active library (``format_insight_library``) and each
  lesson / improvement / rule suggestion names the ids it reinforces;
* ``split_insight_items`` keeps the stored review lists as plain strings and records
  the links under ``content_json["insight_links"]``;
* ``reinforce`` counts one reinforcing review as one validated case, once per review;
* ``reverse_review`` undoes a deleted review's cases.

Merging similar insights lives in ``insight_merge``.
"""
from __future__ import annotations

import json
import logging
import re

from datetime import datetime
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

LIBRARY_LIMIT = 60
# (section, list, category) — the review lists that become insights.
INSIGHT_LISTS = (
    ("lessons_learned", "lessons", "process"),
    ("lessons_learned", "improvements", "process"),
    ("rule_updates", "suggestions", "strategy"),
)

_LIBRARY_HEADER = {
    "en": (
        "## Insight library (existing lessons and rules, by id)\n"
        "When an item you write restates one of these, list its id in \"reinforces\": someone "
        "reading both would call one a restatement or refinement of the other. Sharing an asset, "
        "a theme or a cause is not enough."
    ),
    "zh-CN": (
        "## 洞察库（已有的经验与准则，按编号）\n"
        "你写的条目若重申其中某条，请把它的编号写进 \"reinforces\"：读者看两条会认为一条是另一条的"
        "重述或细化。只是涉及同一资产、同一主题或同一原因，不算。"
    ),
}


# ---------------------------------------------------------------------------
# Prompt side
# ---------------------------------------------------------------------------

def format_insight_library(conn, language: Optional[str] = None, limit: int = LIBRARY_LIMIT) -> str:
    """The active library as prompt lines: ``#id [status] title``; '' when empty."""
    try:
        rows = conn.execute(
            """
            SELECT id, status, title FROM ai_insights
            WHERE status IN ('raw', 'recurring', 'validated', 'principle')
            ORDER BY CASE status WHEN 'principle' THEN 0 WHEN 'validated' THEN 1
                                 WHEN 'recurring' THEN 2 ELSE 3 END,
                     created_at DESC, id DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
    except Exception as e:  # table missing on a fresh DB
        logger.warning("insight library query failed: %s", e)
        return ""
    if not rows:
        return ""
    header = _LIBRARY_HEADER.get(language or "zh-CN", _LIBRARY_HEADER["zh-CN"])
    lines = [f"#{i} [{s}] {' '.join(str(t).split())}" for i, s, t in rows]
    return header + "\n" + "\n".join(lines)


def _ids(value: Any) -> list[int]:
    out: list[int] = []
    for v in value if isinstance(value, list) else [value] if value is not None else []:
        try:
            n = int(str(v).lstrip("#"))
        except (TypeError, ValueError):
            continue
        if n not in out:
            out.append(n)
    return out


def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value] if value else []
    return [str(v).strip() for v in items if isinstance(v, (str, int)) and str(v).strip()]


def split_insight_items(content_json: dict) -> dict:
    """Flatten object items to strings and record their links (idempotent).

    Accepts ``{"text", "reinforces", "assets"}`` objects or plain strings. The three
    lists are stored as plain strings so the review page and markdown are unchanged.
    """
    if "insight_links" in content_json:
        return content_json
    links: list[dict] = []
    for section_key, list_key, category in INSIGHT_LISTS:
        section = content_json.get(section_key)
        if not isinstance(section, dict) or not isinstance(section.get(list_key), list):
            continue
        flat: list[str] = []
        for item in section[list_key]:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("title") or item.get("description") or "").strip()
                reinforces, assets = _ids(item.get("reinforces")), _strings(item.get("assets"))
            elif isinstance(item, str):
                text, reinforces, assets = item.strip(), [], []
            else:
                continue
            if not text:
                continue
            links.append({"section": section_key, "list": list_key, "index": len(flat),
                          "text": text, "category": category,
                          "reinforces": reinforces, "assets": assets})
            flat.append(text)
        section[list_key] = flat
    content_json["insight_links"] = links
    return content_json


def insight_items(content_json: dict) -> list[dict]:
    """The review's insight items with links (older reviews: plain strings, no links)."""
    links = content_json.get("insight_links")
    if isinstance(links, list):
        return [x for x in links if isinstance(x, dict) and str(x.get("text") or "").strip()]
    copy = {k: (dict(v) if isinstance(v, dict) else v) for k, v in content_json.items()}
    return split_insight_items(copy)["insight_links"]


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------

def _links(raw: Any) -> list[dict]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _refs(raw: Optional[str]) -> list[str]:
    return [r.strip() for r in str(raw or "").split(",") if r.strip()]


def _join_refs(*groups: Iterable[str]) -> Optional[str]:
    out: list[str] = []
    for group in groups:
        for ref in group:
            if ref and ref not in out:
                out.append(ref)
    return ",".join(out) or None


_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,11}$")


def resolve_assets(conn, names: Iterable[str]) -> list[str]:
    """Canonical asset ids for what the model wrote; unknown names are dropped.

    Exact id or display name first. A ticker or fund code ("SGOV", "BRK-B", "110020")
    matches the ids ending in it (US_STK_SGOV, CN_FUND_110020; AMZN → RSU_AMZN and
    US_STK_AMZN): every registry id is <prefix>_<ticker or code>.
    """
    out: list[str] = []
    for written in names:
        written = str(written).strip()
        # "Amazon RSU (AMZN)" / "ISHARES 0-3 MONTH ... (SGOV)": try the whole, then each part.
        bracket = re.match(r"^(.*?)\s*[(（]\s*([^()（）]+?)\s*[)）]$", written)
        candidates = [written] + ([bracket.group(1), bracket.group(2)] if bracket else [])
        for name in candidates:
            found = _resolve_one(conn, name)
            if found is None:
                return out
            out.extend(i for i in found if i not in out)
            if found:
                break
    return out


def _resolve_one(conn, name: str) -> Optional[list[str]]:
    """Registry ids for one written name; None when the registry cannot be read."""
    if not name:
        return []
    try:
        ids = [r[0] for r in conn.execute(
            """SELECT canonical_id FROM asset_registry
               WHERE LOWER(canonical_id) = LOWER(?) OR display_name = ?
               ORDER BY (LOWER(canonical_id) = LOWER(?)) DESC LIMIT 1""",
            [name, name, name],
        ).fetchall()]
        if not ids and _TICKER.match(name):
            ids = [r[0] for r in conn.execute(
                """SELECT canonical_id FROM asset_registry
                   WHERE UPPER(canonical_id) LIKE '%\\_' || UPPER(?) ESCAPE '\\'
                   ORDER BY canonical_id LIMIT 3""",
                [name],
            ).fetchall()]
    except Exception:
        return None
    return ids


def report_ids_of(source_report_id: Optional[int], links: list[dict]) -> set[int]:
    """Reviews already counted for an insight: the one that created it plus its cases."""
    seen = {int(x["report_id"]) for x in links if isinstance(x.get("report_id"), int)}
    if source_report_id is not None:
        seen.add(int(source_report_id))
    return seen


def reinforce(conn, insight_id: int, report_id: int, note: str, assets: Iterable[str] = ()) -> bool:
    """Count ``report_id`` as one validated case of ``insight_id`` (once per review).

    Returns True when a case was added. Assets are merged even when it was not.
    """
    row = conn.execute(
        """SELECT recurrence_count, status, validated_case_links, source_report_id, entity_refs
           FROM ai_insights WHERE id = ? AND status <> 'deprecated'""",
        [insight_id],
    ).fetchone()
    if row is None:
        return False
    recurrence, status, raw_links, source_report_id, entity_refs = row
    links = _links(raw_links)
    refs = _join_refs(_refs(entity_refs), assets)
    if int(report_id) in report_ids_of(source_report_id, links):
        if refs != entity_refs:
            conn.execute("UPDATE ai_insights SET entity_refs = ? WHERE id = ?", [refs, insight_id])
        return False
    new_recurrence = int(recurrence or 1) + 1
    case = {"source": "review", "report_id": int(report_id), "link": f"review #{report_id}",
            "note": (note or "")[:300], "added_at": datetime.now().isoformat()}
    if status == "raw" and new_recurrence >= 2:
        case["raised_status"] = True  # deleting this review puts it back to raw
    links.append(case)
    conn.execute(
        """UPDATE ai_insights
           SET recurrence_count = ?, validated_cases = COALESCE(validated_cases, 0) + 1,
               validated_case_links = ?, entity_refs = ?,
               status = CASE WHEN status = 'raw' AND ? >= 2 THEN 'recurring' ELSE status END,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        [new_recurrence, json.dumps(links, ensure_ascii=False), refs, new_recurrence, insight_id],
    )
    return True


def reverse_review(conn, report_id: int) -> int:
    """Remove a deleted review's cases from every insight; returns how many were removed."""
    removed = 0
    rows = conn.execute(
        """SELECT id, validated_case_links, recurrence_count FROM ai_insights
           WHERE validated_case_links IS NOT NULL"""
    ).fetchall()
    for insight_id, raw, recurrence in rows:
        links = _links(raw)
        kept = [x for x in links if x.get("report_id") != int(report_id)]
        n = len(links) - len(kept)
        if not n:
            continue
        lowered = any(x.get("raised_status") for x in links if x.get("report_id") == int(report_id))
        if lowered and int(recurrence or 1) - n >= 2:
            # Another review still repeats it: it stays recurring, and that review's case
            # now carries the flag in case it is deleted too.
            lowered = False
            heir = next((x for x in reversed(kept) if x.get("source") == "review"), None)
            if heir is not None:
                heir["raised_status"] = True
        conn.execute(
            """UPDATE ai_insights
               SET validated_cases = GREATEST(COALESCE(validated_cases, 0) - ?, 0),
                   recurrence_count = GREATEST(COALESCE(recurrence_count, 1) - ?, 1),
                   status = CASE WHEN ? AND status = 'recurring' THEN 'raw' ELSE status END,
                   validated_case_links = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            [n, n, lowered, json.dumps(kept, ensure_ascii=False), insight_id],
        )
        removed += n
    return removed


def title_and_body(text: str) -> tuple[str, str]:
    """Title is the first 80 characters; the body keeps the full text when longer.

    Same cut as before 2026-11-09, so a same-title match still finds older rows.
    """
    text = text.strip()
    return (text[:80], text) if len(text) > 80 else (text, "")
