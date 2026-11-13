"""Merging similar insights (2026-11-09, docs/api-specs/insight-reinforcement.md A3/A4).

``similar_groups`` asks the model which active insights state the same rule; the owner
approves each group (editing the model's combined wording if needed), and ``merge_group``
folds the members into the kept insight: it takes the combined wording, lists what it
absorbed in ``merged_from``, and carries each review behind the members over as one case.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from src.services.ai_advisor.insight_reinforcement import (
    _ids,
    _join_refs,
    _links,
    _refs,
    report_ids_of,
    title_and_body,
)

_STATUS_RANK = {"principle": 0, "validated": 1, "recurring": 2, "raw": 3}

_ROW_SQL = """SELECT id, status, title, category, source_report_id, validated_cases,
                     validated_case_links, recurrence_count, tags, entity_refs, confidence, created_at,
                     body, merged_from
              FROM ai_insights WHERE id = ?"""


def _row(conn, insight_id: int) -> Optional[dict]:
    r = conn.execute(_ROW_SQL, [insight_id]).fetchone()
    if r is None:
        return None
    keys = ("id", "status", "title", "category", "source_report_id", "validated_cases",
            "validated_case_links", "recurrence_count", "tags", "entity_refs", "confidence", "created_at",
            "body", "merged_from")
    row = dict(zip(keys, r))
    row["links"] = _links(row["validated_case_links"])
    row["merged"] = _links(row["merged_from"])
    row["text"] = row["body"] or row["title"]  # the title is cut at 80 characters
    return row


def _absorbed(row: dict, now: str, replaced: bool = False) -> dict:
    entry = {"id": row["id"], "title": row["text"], "report_id": row["source_report_id"], "merged_at": now}
    if replaced:
        entry["replaced_wording"] = True  # the kept insight's own wording before the merge
    return entry


def merge_plan(primary: dict, members: list[dict]) -> list[dict]:
    """Case entries the primary gains from ``members`` (each review counted once)."""
    seen = report_ids_of(primary["source_report_id"], primary["links"])
    added: list[dict] = []
    now = datetime.now().isoformat()
    for m in members:
        evidence = [m["source_report_id"]] + [x.get("report_id") for x in m["links"]]
        for rid in evidence:
            if isinstance(rid, int) and rid not in seen:
                seen.add(rid)
                added.append({"source": "merge", "report_id": rid, "merged_id": m["id"],
                              "link": f"review #{rid}", "note": m["title"][:300], "added_at": now})
        # Cases the owner added by hand (no review behind them) carry over as they are.
        added.extend(dict(x, merged_id=m["id"]) for x in m["links"] if "report_id" not in x)
    return added


def merge_group(conn, primary_id: int, member_ids: list[int], title: Optional[str] = None) -> int:
    """Deprecate ``member_ids`` into ``primary_id`` (one transaction). Returns cases added.

    ``title``: the combined wording for the kept insight (the owner may have edited the
    model's proposal). Its previous wording goes into ``merged_from`` with the members.

    Raises LookupError when the primary is missing, ValueError for a bad member list.
    """
    primary = _row(conn, primary_id)
    if primary is None:
        raise LookupError(f"Insight {primary_id} not found")
    if primary["status"] == "deprecated":
        raise ValueError(f"Insight {primary_id} is deprecated")
    ids = list(dict.fromkeys(int(i) for i in member_ids))
    if not ids:
        raise ValueError("member_ids is empty")
    if primary_id in ids:
        raise ValueError("member_ids contains the kept insight")
    members = []
    for i in ids:
        m = _row(conn, i)
        if m is None or m["status"] == "deprecated":
            raise ValueError(f"Insight {i} is missing or already merged")
        members.append(m)

    added = merge_plan(primary, members)
    new_reviews = sum(1 for a in added if "report_id" in a)
    recurrence = int(primary["recurrence_count"] or 1) + new_reviews
    tags = _join_refs(_refs(primary["tags"]), *(_refs(m["tags"]) for m in members))
    refs = _join_refs(_refs(primary["entity_refs"]), *(_refs(m["entity_refs"]) for m in members))
    now = datetime.now().isoformat()
    merged = list(primary["merged"])
    wording = " ".join(str(title or "").split())
    new_title, new_body = primary["title"], primary["body"]
    if wording and wording != primary["text"]:
        merged.append(_absorbed(primary, now, replaced=True))
        new_title, new_body = title_and_body(wording)
    for m in members:
        merged.append(_absorbed(m, now))
        merged.extend(m["merged"])  # what an earlier merge had folded into the member
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(
            """UPDATE ai_insights
               SET validated_cases = COALESCE(validated_cases, 0) + ?, validated_case_links = ?,
                   recurrence_count = ?, tags = ?, entity_refs = ?, title = ?, body = ?,
                   merged_from = ?,
                   status = CASE WHEN status = 'raw' AND ? >= 2 THEN 'recurring' ELSE status END,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            [len(added), json.dumps(primary["links"] + added, ensure_ascii=False),
             recurrence, tags, refs, new_title, new_body or "",
             json.dumps(merged, ensure_ascii=False), recurrence, primary_id],
        )
        for m in members:
            conn.execute(
                "UPDATE ai_insights SET status = 'deprecated', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [m["id"]],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(added)


# ---------------------------------------------------------------------------
# Similar-insight groups (model-proposed, owner-approved)
# ---------------------------------------------------------------------------

_GROUPS_SYSTEM = (
    "You curate an investor's library of lessons and rules. Group the insights that state the "
    "same rule or lesson in different words (or languages). A later refinement, amendment or "
    "tightening of a rule belongs with that rule. Do not group insights that only share a topic "
    "but ask for different actions. Leave an insight out when nothing else says the same.\n"
    "For each group also write \"rule\": the group's rule as one clear, actionable sentence that "
    "keeps every concrete threshold the insights give (numbers, levels, percentages).\n"
    'Return JSON only: {"groups": [{"theme": "short label", "rule": "...", "ids": [id, id, ...]}]}. '
    "Each group has at least two ids; each id appears in at most one group."
)


def _report_dates(conn, report_ids: set[int]) -> dict[int, str]:
    if not report_ids:
        return {}
    marks = ",".join("?" for _ in report_ids)
    rows = conn.execute(
        f"SELECT id, CAST(created_at AS DATE) FROM ai_reports WHERE id IN ({marks})", list(report_ids)
    ).fetchall()
    return {int(i): str(d) for i, d in rows}


def build_groups(conn, proposed: Any) -> list[dict]:
    """Validate the model's groups against the library and add the merge outcome."""
    active = {
        int(r[0]): r for r in conn.execute(
            "SELECT id FROM ai_insights WHERE status IN ('raw','recurring','validated','principle')"
        ).fetchall()
    }
    used: set[int] = set()
    raw_groups = proposed.get("groups") if isinstance(proposed, dict) else proposed
    groups: list[dict] = []
    for g in raw_groups if isinstance(raw_groups, list) else []:
        if not isinstance(g, dict):
            continue
        ids = [i for i in _ids(g.get("ids")) if i in active and i not in used]
        if len(ids) < 2:
            continue
        rows = [_row(conn, i) for i in ids]
        rows.sort(key=lambda r: (_STATUS_RANK.get(r["status"], 9), str(r["created_at"]), r["id"]))
        primary, members = rows[0], rows[1:]
        added = merge_plan(primary, members)
        cases = int(primary["validated_cases"] or 0) + len(added)
        confidence = float(primary["confidence"]) if primary["confidence"] is not None else 0.3
        used.update(ids)
        rule = " ".join(str(g.get("rule") or "").split())
        groups.append({"theme": str(g.get("theme") or "").strip()[:80],
                       "merged_title": rule[:300] or primary["text"],
                       "primary_id": primary["id"], "rows": rows,
                       "cases_after_merge": cases,
                       "promotable_after_merge": cases >= 3 or confidence >= 0.70})
    dates = _report_dates(conn, {r["source_report_id"] for g in groups for r in g["rows"]
                                 if r["source_report_id"] is not None})
    for g in groups:
        g["members"] = [{"id": r["id"], "title": r["title"], "status": r["status"],
                         "category": r["category"], "source_report_id": r["source_report_id"],
                         "report_date": dates.get(r["source_report_id"])} for r in g.pop("rows")]
    return groups


def similar_groups(connect, language: Optional[str], client=None) -> dict:
    """Ask the model to group similar active insights. Read-only.

    ``connect`` opens a read connection. None is held across the model call: the LLM
    client writes its usage log to the same database file.
    """
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT id, status, category, title FROM ai_insights
               WHERE status IN ('raw','recurring','validated','principle') ORDER BY id"""
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < 2:
        return {"groups": [], "considered": len(rows), "model_used": ""}
    if client is None:
        from src.services.llm_client import LLMClient
        client = LLMClient()
    label_lang = "Simplified Chinese" if (language or "zh-CN").startswith("zh") else "English"
    user = (f"Write each theme (at most 20 characters) and rule in {label_lang}.\n\nInsights:\n"
            + "\n".join(f"#{i} [{s}/{c}] {' '.join(str(t).split())}" for i, s, c, t in rows))
    response = client.complete(system_prompt=_GROUPS_SYSTEM, user_prompt=user,
                               expect_json=True, report_type="insight_groups")
    payload = getattr(response, "content_json", None)
    if not getattr(response, "success", True) or not isinstance(payload, (dict, list)):
        raise RuntimeError(getattr(response, "error", None) or "the model returned no groups")
    conn = connect()
    try:
        groups = build_groups(conn, payload)
    finally:
        conn.close()
    return {"groups": groups, "considered": len(rows),
            "model_used": getattr(response, "model_used", "") or ""}
