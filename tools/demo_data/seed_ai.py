#!/usr/bin/env python3
"""Deterministic demo AI-advisor content seeder (Round 5 finding #3, Phase 3a/3b).

The quickstart demo builds a synthetic persona (tools/demo_data/persona.yaml
+ generate.py -> reader fixtures -> sync) but that pipeline only produces
holdings/transactions data. The AI Advisor — the product's headline feature —
is empty on a fresh demo install: no investor profile, no strategy memos, no
briefs/reviews/insights. This script is a separate, explicit, deterministic
seeding step that fills in the investor profile and strategy memos (Phase 3a)
and, as of Phase 3b, ONE sample daily Brief and ONE sample completed Review —
so a new user without an LLM API key can see what the AI Advisor's output
looks like before ever configuring a key. Both sample rows are written with
``model_used = 'demo-sample'`` (see ``DEMO_SAMPLE_MODEL_MARKER`` below), which
the frontend (``ux-command-center/pages/AIAdvisor.tsx`` and
``components/ai-advisor/ReviewFlow.tsx``) uses to render a "Sample" badge —
this is never mistaken for a real AI-generated report.

All content lives in tools/demo_data/ai_seed.yaml, written in the persona's
voice and consistent with persona.yaml's holdings, targets, and timeline —
nothing here is hard-coded content, only plumbing.

Usage:
    .venv/bin/python tools/demo_data/seed_ai.py [--db PATH] [--dry-run]

--db defaults to the same resolution the app itself uses
(src.database.connector.resolve_db_path with its DEFAULT_DB_PATH sentinel —
worktree-safe project root, UIS_DB_PATH env override, then data/unified.duckdb).

SAFETY GUARD (mandatory, positive marker only):
This script refuses to write unless the target DB is clearly the demo
persona's own database. The marker is holdings.account =
'IBKR_U0000123' — 'U0000123' is the demo persona's fictional IBKR account id
(tools/demo_data/persona.yaml identity.ibkr_account), and
src/sources/hooks/ibkr.py writes holdings.account as f"IBKR_{account_id}" for
every IBKR-sourced holdings row. That exact string only appears in a database
that has synced the persona's synthetic IBKR Flex fixture; a real owner's
database has their own real IBKR account number there instead. If the marker
is absent (table missing, DB missing/unreadable, or no matching row), the
script exits non-zero and writes nothing — this is a positive-evidence check,
never an absence-of-something-else check.

IDEMPOTENCY:
- user_profile is the app's existing single-row-by-design table (id=1);
  written with the same ON CONFLICT(id) DO UPDATE upsert pattern
  src.services.settings_manager.save_profile already uses.
- strategy_memos is upserted on its own UNIQUE(memo_date, title) constraint
  (ON CONFLICT DO UPDATE) — the same natural key the app's own
  POST /strategy/memos route relies on. Every row this script writes also
  carries source_file = 'tools/demo_data/seed_ai.py' as a stable ownership
  marker, so the rows this script owns are always identifiable without
  relying on title text alone.
- memo_registry / memo_asset_map use the same idempotent upsert pattern
  src.database.seed_loader.seed_demo_content already uses for the sibling
  (env-var-gated) seed-pack system: ON CONFLICT(memo_id) DO UPDATE for
  memo_registry, INSERT ... WHERE NOT EXISTS for memo_asset_map.
- ai_reports (Phase 3b sample brief/review): this table has no natural
  unique key to ON CONFLICT against (id is a bare sequence), so the marker
  itself — the single row per report_type carrying
  ``model_used = 'demo-sample'`` — IS the natural key: look it up, UPDATE if
  found, INSERT if not. Exactly one demo-sample brief and one demo-sample
  review ever exist; a real generated report always carries the LLM's own
  model_used string and is therefore never touched by this script.
Running this script twice yields identical row counts and content — no rows
outside these natural keys are ever touched.

DETERMINISTIC: no randomness. All content is static in ai_seed.yaml; editing
that file is the only way to change what gets written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.database.connector import (  # noqa: E402
    DEFAULT_DB_PATH,
    DatabaseConnector,
    resolve_db_path,
)

# Phase 3b: sample report seeding (imports called by seed_all)
from tools.demo_data.seed_ai_reports import seed_sample_reports  # noqa: E402

# Phase 3c: insights lifecycle + Decision Hub bridge (imports called by seed_all)
from tools.demo_data.seed_ai_insights import seed_insights_and_trades  # noqa: E402

SEED_FILE = Path(__file__).resolve().parent / "ai_seed.yaml"

# Ownership marker written to strategy_memos.source_file for every row this
# script writes/updates — lets a future cleanup tool find "rows this script
# owns" without relying on title text.
SOURCE_MARKER = "tools/demo_data/seed_ai.py"

# model_used marker written to the Phase 3b sample brief/review rows in
# ai_reports. A real generated report always carries the LLM's own
# model_used string (e.g. "gemini/gemini-2.5-flash"), so this value can never
# collide with one — it both identifies "the demo-sample row for this
# report_type" (this script's idempotency key, see module docstring) AND is
# what the frontend badge (ux-command-center aiAdvisor.json "demoSample" keys)
# checks for to label the content as a sample rather than a real AI output.
DEMO_SAMPLE_MODEL_MARKER = "demo-sample"

# Demo persona's IBKR account id (tools/demo_data/persona.yaml
# identity.ibkr_account = "U0000123"), as it appears in holdings.account
# after src/sources/hooks/ibkr.py writes f"IBKR_{account_id}". See module
# docstring "SAFETY GUARD" for why this is a safe positive marker.
DEMO_MARKER_ACCOUNT = "IBKR_U0000123"

# Phase 3c ownership marker appended to ai_insights.tags (that table has no
# dedicated source-file column like strategy_memos does) — lets a future
# cleanup tool find "insights this script owns" without relying on title
# text alone, same intent as SOURCE_MARKER above.
INSIGHT_TAG_MARKER = "demo-seed:tools/demo_data/seed_ai.py"


REQUIRED_SEED_KEYS = ("investor_profile", "strategy_memos", "sample_brief", "sample_review")


def load_seed() -> dict[str, Any]:
    with open(SEED_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or any(key not in data for key in REQUIRED_SEED_KEYS):
        raise ValueError(f"{SEED_FILE} is missing required top-level keys")
    return data


def has_demo_marker(db_path: str) -> bool:
    """True iff `holdings.account` carries the demo persona's IBKR account id.

    Any failure to prove the marker's presence (missing file, missing table,
    connection error) is treated the same as "marker absent" — this function
    only ever asserts positive evidence, never infers safety from the
    absence of something else.
    """
    try:
        db = DatabaseConnector(db_path, read_only=True)
    except Exception:
        return False
    try:
        row = db.execute(
            "SELECT 1 FROM holdings WHERE account = ? LIMIT 1",
            [DEMO_MARKER_ACCOUNT],
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        db.close()


def _truncate(text: str, width: int = 88) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def describe_seed(seed: dict[str, Any]) -> list[str]:
    """Human-readable lines describing what `seed_all` would write. Used by
    both --dry-run output and the test suite's assertions."""
    lines: list[str] = []
    profile = seed["investor_profile"]
    lines.append(
        f"user_profile id=1: display_name={profile.get('display_name')!r}, "
        f"language={profile.get('language', 'en')!r}"
    )
    for key, value in profile["philosophy"].items():
        lines.append(f"  philosophy.{key}: {_truncate(value)}")
    for memo in seed["strategy_memos"]:
        lines.append(
            f"strategy_memos: {memo['memo_date']} · {memo['title']} "
            f"[{memo['strategic_bias']}] (source_file={SOURCE_MARKER})"
        )
    for entry in seed.get("memo_registry", []):
        assets = ", ".join(entry.get("linked_assets", []))
        lines.append(f"memo_registry: {entry['memo_id']} · {entry['title']} -> [{assets}]")
    sample_brief = seed.get("sample_brief")
    if sample_brief:
        lines.append(
            f"ai_reports (brief, model_used={DEMO_SAMPLE_MODEL_MARKER!r}): "
            f"{sample_brief.get('title')!r} [{', '.join(sample_brief['content_json'].keys())}]"
        )
    sample_review = seed.get("sample_review")
    if sample_review:
        lines.append(
            f"ai_reports (review, model_used={DEMO_SAMPLE_MODEL_MARKER!r}): "
            f"{sample_review.get('title')!r} "
            f"[{sample_review.get('period_start')} - {sample_review.get('period_end')}] "
            f"[{', '.join(sample_review['content_json'].keys())}]"
        )
    for insight in seed.get("insights_lifecycle", []):
        lines.append(
            f"ai_insights: {insight['created_at']} · {insight['title']!r} "
            f"[{insight['status']}, category={insight['category']}, "
            f"confidence={insight.get('confidence')}, "
            f"validated_cases={insight.get('validated_cases', 0)}]"
        )
    for adoption in seed.get("insight_adoptions", []):
        lines.append(
            f"insights (bridged, adopted={adoption['adopted']}): {adoption['title']!r}"
        )
    for trade in seed.get("trade_logs", []):
        lines.append(
            f"trade_logs: {trade['log_date']} · {trade['action']} {trade['asset_id']} "
            f"[verdict={trade.get('verdict')}, source={trade.get('suggestion_source')}]"
        )
    return lines


def seed_investor_profile(db: DatabaseConnector, profile: dict[str, Any]) -> None:
    philosophy_json = json.dumps(profile["philosophy"], ensure_ascii=False)
    existing = db.execute("SELECT display_name FROM user_profile WHERE id = 1").fetchone()
    # Never clobber a display_name a real user already set on this DB;
    # only fill it in when the row is new / the field is still blank.
    display_name = existing[0] if existing and existing[0] else profile.get("display_name")
    db.execute(
        """
        INSERT INTO user_profile (id, display_name, philosophy, language, updated_at)
        VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            display_name = excluded.display_name,
            philosophy = excluded.philosophy,
            language = excluded.language,
            updated_at = excluded.updated_at
        """,
        [display_name, philosophy_json, profile.get("language", "en")],
    )


def seed_strategy_memos(db: DatabaseConnector, memos: list[dict[str, Any]]) -> None:
    for memo in memos:
        db.execute(
            """
            INSERT INTO strategy_memos
                (memo_date, title, strategic_bias, key_directives, content, source_file)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (memo_date, title) DO UPDATE SET
                strategic_bias = excluded.strategic_bias,
                key_directives = excluded.key_directives,
                content = excluded.content,
                source_file = excluded.source_file
            """,
            [
                memo["memo_date"],
                memo["title"],
                memo["strategic_bias"],
                json.dumps(memo.get("key_directives", []), ensure_ascii=False),
                memo["content"],
                SOURCE_MARKER,
            ],
        )


def seed_memo_registry(db: DatabaseConnector, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        db.execute(
            """
            INSERT INTO memo_registry (memo_id, title, status, falsification_summary, doc_link)
            VALUES (?, ?, 'active', ?, NULL)
            ON CONFLICT (memo_id) DO UPDATE SET
                title = excluded.title,
                falsification_summary = excluded.falsification_summary,
                status = excluded.status
            """,
            [entry["memo_id"], entry["title"], entry.get("falsification_summary")],
        )
        for asset_id in entry.get("linked_assets", []):
            db.execute(
                """
                INSERT INTO memo_asset_map (memo_id, asset_id)
                SELECT ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM memo_asset_map WHERE memo_id = ? AND asset_id = ?
                )
                """,
                [entry["memo_id"], asset_id, entry["memo_id"], asset_id],
            )




def seed_all(db: DatabaseConnector, seed: dict[str, Any]) -> None:
    seed_investor_profile(db, seed["investor_profile"])
    seed_strategy_memos(db, seed["strategy_memos"])
    seed_memo_registry(db, seed.get("memo_registry", []))
    seed_sample_reports(db, seed)
    seed_insights_and_trades(db, seed)


def run(db_arg: str, dry_run: bool) -> int:
    seed = load_seed()
    resolved = resolve_db_path(db_arg)

    if not has_demo_marker(resolved):
        print(
            f"seed_ai: refusing to write — {resolved!r} does not carry the demo "
            f"persona's IBKR marker ({DEMO_MARKER_ACCOUNT!r} in holdings.account). "
            "This does not look like the demo persona's database (run the "
            "quickstart generate+sync first, or point --db at the right file). "
            "Writing nothing.",
            file=sys.stderr,
        )
        return 1

    lines = describe_seed(seed)
    if dry_run:
        print(f"[dry-run] target DB: {resolved}")
        for line in lines:
            print(f"[dry-run] {line}")
        print("[dry-run] no changes written")
        return 0

    db = DatabaseConnector(resolved, read_only=False)
    try:
        seed_all(db, seed)
    finally:
        db.close()

    print(f"seed_ai: wrote demo AI content to {resolved}")
    for line in lines:
        print(f"  {line}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help="Target DuckDB path (default: same resolution the app uses)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing anything",
    )
    args = parser.parse_args()
    return run(args.db, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
