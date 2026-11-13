"""Append-only sync log (audit 2026-11-08 issue 7, owner decision).

Each sync appends one row to ``sync_metrics_log``: when it ran, a SHA-256 of
every ledger input file the readers read, and the headline figures — TWR,
XIRR, YTD, 1Y and closing value for each returns window, lifetime P&L and net
worth. When a closed period's numbers change (the 11/6 → 11/8 TWR 34.55% →
34.43% case), comparing two rows names the input file that changed.

Never raises into the sync: a failure is logged and the sync carries on.
Rows are only ever inserted; nothing here updates or deletes them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_FILES_PER_PATTERN = 200
WINDOWS = ("all_time", "last_12m", "last_36m")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ledger_input_hashes(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{source_key: {file name: {sha256, bytes}}} for every enabled reader input.

    Resolves files the way the readers do: the source's ``data_dir`` (or
    ``finance_dir``) joined with each ``file_patterns`` entry, which is either a
    workbook name or a glob (CSV exports). A missing file is recorded as such.
    """
    finance_dir = config.get("finance_dir") or config.get("sources", {}).get("pis", {}).get("finance_dir")
    out: Dict[str, Dict[str, Any]] = {}
    for source_key, cfg in sorted((config.get("source_registry") or {}).items()):
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            continue
        base = cfg.get("data_dir") or finance_dir
        patterns = cfg.get("file_patterns") or {}
        files: Dict[str, Any] = {}
        if not base or not patterns:
            out[source_key] = {"_status": "no_input_configured"}
            continue
        base_path = Path(str(base))
        for pattern in patterns.values():
            matches = sorted(p for p in base_path.glob(str(pattern)) if p.is_file())
            if not matches:
                files[str(pattern)] = {"missing": True}
            for path in matches[-_MAX_FILES_PER_PATTERN:]:
                try:
                    files[path.name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
                except OSError as exc:
                    files[path.name] = {"error": str(exc)}
        out[source_key] = files
    return out


def headline_metrics(db) -> Dict[str, Any]:
    """The figures the owner reconciles against, as the pages show them."""
    from src.services.investment_returns import build_investment_returns
    from src.services.pnl import Scope, compute_portfolio_pnl, summary_totals
    from src.services.rebalanceable_filter import fetch_non_rebalanceable_asset_ids

    metrics: Dict[str, Any] = {"returns": {}}
    for window in WINDOWS:
        try:
            r = build_investment_returns(db, window)
        except Exception as exc:  # one window failing must not drop the others
            metrics["returns"][window] = {"error": str(exc)}
            continue
        bridge = r.get("investment_bridge") or {}
        metrics["returns"][window] = {
            "period_start": r.get("twr_period_start"),
            "as_of": r.get("twr_as_of"),
            "twr_cumulative": r.get("twr_cumulative"),
            "twr_annualized": r.get("twr_annualized"),
            "xirr": r.get("mwr_xirr"),
            "twr_ytd": r.get("twr_ytd"),
            "twr_1y": r.get("twr_1y"),
            "opening_value_cny": bridge.get("opening_value_cny"),
            "closing_value_cny": bridge.get("closing_value_cny"),
            "net_external_flow_cny": bridge.get("net_external_flow_cny"),
            "investment_gain_cny": bridge.get("investment_gain_cny"),
        }
    portfolio = compute_portfolio_pnl(db, scope=Scope())
    for label, exclude in (("all_assets", False), ("rebalanceable", True)):
        totals = summary_totals(
            portfolio.assets,
            excluded_ids=fetch_non_rebalanceable_asset_ids(db) if exclude else frozenset(),
            apply_name_filter=exclude,
        )
        metrics[label] = {
            "net_worth": totals["net_worth"],
            "lifetime_pl": totals["total_lifetime"],
            "unrealized_pl": totals["total_unrealized"],
            "realized_pl": totals["total_realized"],
        }
    metrics["snapshot_date"] = str(portfolio.snapshot_date) if portfolio.snapshot_date else None
    metrics["usd_cny"] = portfolio.today_fx
    return metrics


def record_sync_metrics(db, config: Dict[str, Any], *, trigger: str = "sync",
                        note: Optional[str] = None) -> Optional[int]:
    """Append one row; returns its id, or None when it could not be written.

    ``trigger`` names what caused the row: ``sync``, or an owner action such as
    ``twr_rereview``, ``ttfund_cli_import`` or ``ttfund_attestation`` (``note`` says what).
    """
    try:
        source = db.execute(
            "SELECT input_fingerprint, source_sha256 FROM investment_twr_source WHERE id = 1"
        ).fetchone()
    except Exception:
        source = None
    try:
        row = db.execute(
            """INSERT INTO sync_metrics_log
               (recorded_at, trigger, app_version, input_fingerprint, funding_source_sha256,
                ledger_hashes, metrics, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            [
                datetime.now(timezone.utc).replace(tzinfo=None),  # stored as naive UTC
                trigger,
                os.environ.get("APP_VERSION") or None,
                source[0] if source else None,
                source[1] if source else None,
                json.dumps(ledger_input_hashes(config), ensure_ascii=False, sort_keys=True),
                json.dumps(headline_metrics(db), ensure_ascii=False, sort_keys=True, default=str),
                note,
            ],
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        logger.exception("sync metrics log: row not written")
        return None


def _changed_files(newer: Dict[str, Any], older: Dict[str, Any]) -> List[str]:
    changed = []
    for source in sorted(set(newer) | set(older)):
        a, b = newer.get(source) or {}, older.get(source) or {}
        for name in sorted(set(a) | set(b)):
            if (a.get(name) or {}).get("sha256") != (b.get(name) or {}).get("sha256"):
                state = "added" if name not in b else "removed" if name not in a else "changed"
                changed.append(f"{source}/{name} ({state})")
    return changed


def list_sync_metrics(db, limit: int = 20) -> List[Dict[str, Any]]:
    """Newest first, each with the ledger files changed since the row before it."""
    rows = db.execute(
        "SELECT id, recorded_at, trigger, app_version, input_fingerprint, funding_source_sha256, "
        "ledger_hashes, metrics, note FROM sync_metrics_log ORDER BY id DESC LIMIT ?",
        [int(limit) + 1],
    ).fetchall()
    parsed = []
    for r in rows:
        parsed.append({
            "id": r[0],
            "recorded_at": r[1].replace(tzinfo=timezone.utc).isoformat() if r[1] else None,
            "trigger": r[2],
            "app_version": r[3],
            "input_fingerprint": r[4],
            "funding_source_sha256": r[5],
            "ledger_hashes": json.loads(r[6]) if isinstance(r[6], str) else (r[6] or {}),
            "metrics": json.loads(r[7]) if isinstance(r[7], str) else (r[7] or {}),
            "note": r[8],
        })
    out = []
    for i, entry in enumerate(parsed[:limit]):
        previous = parsed[i + 1] if i + 1 < len(parsed) else None
        entry["changed_files"] = (
            _changed_files(entry["ledger_hashes"], previous["ledger_hashes"]) if previous else None
        )
        entry["returns_inputs_changed"] = (
            previous is not None and entry["input_fingerprint"] != previous["input_fingerprint"]
        )
        out.append(entry)
    return out
