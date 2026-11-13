"""Returns inputs the user supplies (2026-11-09 follow-up to the P&L audit).

Shown on the Data Sources page; Performance → Returns only links there.

- Re-review the frozen history from the uploaded funding workbook (preview, then apply).
- Import a TTFund ttskill CLI pull (sourced coverage) or record an attestation (attested).

Every write appends a sync-log row naming the action, then re-derives coverage.
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.dependencies import get_db, get_writable_db
from src.api.routes._errors import api_error_response
from src.config import load_config
from src.database.connector import DatabaseConnector
from src.storage.gcs_flush import mark_dirty

logger = logging.getLogger(__name__)
router = APIRouter(tags=["returns-owner"])

_MAX_PULL_BYTES = 5_000_000


class RereviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)
    evidence_ref: str = Field(min_length=1, max_length=500)


class AttestationRequest(BaseModel):
    covered_from: date
    covered_to: date
    note: str = Field(min_length=1, max_length=500)


def _refused(exc: Exception, context: str) -> JSONResponse:
    """422 with the reason. Only the validation messages these modules raise reach
    here (no paths or SQL), and the owner needs them to fix the input."""
    return JSONResponse(status_code=422, content={"error": {"code": f"ERR_{context.upper()}_REFUSED",
                                                            "message": str(exc)[:300]}})


def _log(db, trigger: str, note: str) -> Optional[int]:
    from src.services.sync_metrics_log import record_sync_metrics
    return record_sync_metrics(db, load_config(), trigger=trigger, note=note)


@router.get("/performance/returns-inputs")
async def returns_inputs(db: DatabaseConnector = Depends(get_db)):
    """State for the Data Sources "Investment returns inputs" card (cheap)."""
    from src.financial_analysis.flow_coverage import coverage_status
    from src.financial_analysis.twr_rereview import pending_corrections
    try:
        return {"coverage": coverage_status(db), "corrections": pending_corrections(db, load_config())}
    except Exception as exc:
        logger.exception("returns inputs state failed")
        return api_error_response(exc, context="returns_inputs")


@router.get("/performance/twr-rereview")
async def preview_rereview(db: DatabaseConnector = Depends(get_db)):
    """What a re-review of the frozen window would change (read-only)."""
    from src.financial_analysis.twr_rereview import frozen_window_diff, funding_workbook_path
    try:
        return frozen_window_diff(db, funding_workbook_path(load_config()))
    except Exception as exc:
        logger.exception("re-review preview failed")
        return api_error_response(exc, context="twr_rereview")


@router.post("/performance/twr-rereview")
async def apply_rereview_route(body: RereviewRequest, db: DatabaseConnector = Depends(get_writable_db)):
    from src.financial_analysis.twr_rereview import apply_rereview, funding_workbook_path
    try:
        config = load_config()
        result = apply_rereview(db, funding_workbook_path(config), reviewer=body.reviewer,
                                evidence_ref=body.evidence_ref, config=config)
        mark_dirty()
        return result
    except ValueError as exc:
        return _refused(exc, "twr_rereview")
    except Exception as exc:
        logger.exception("re-review failed")
        return api_error_response(exc, context="twr_rereview")


@router.post("/performance/ttfund-cli-import")
async def import_ttfund_pull(file: UploadFile = File(...), db: DatabaseConnector = Depends(get_writable_db)):
    import json
    from src.financial_analysis.flow_coverage import extend_flow_coverage
    from src.sources.ttfund_cli import import_cli_pull
    try:
        raw = await file.read(_MAX_PULL_BYTES + 1)
        if len(raw) > _MAX_PULL_BYTES:
            raise ValueError("The export is larger than 5 MB")
        result = import_cli_pull(db, raw)
        result["coverage"] = extend_flow_coverage(db)
        result["sync_log_id"] = _log(db, "ttfund_cli_import", json.dumps(
            {"action": "ttfund_cli_import", "file": file.filename, **{k: v for k, v in result.items()
                                                                      if k != "coverage"}}, ensure_ascii=False))
        mark_dirty()
        return result
    except (ValueError, KeyError) as exc:
        return _refused(exc, "ttfund_cli_import")
    except Exception as exc:
        logger.exception("TTFund CLI import failed")
        return api_error_response(exc, context="ttfund_cli_import")


@router.post("/performance/ttfund-attestation")
async def attest_ttfund(body: AttestationRequest, db: DatabaseConnector = Depends(get_writable_db)):
    import json
    from src.financial_analysis.flow_coverage import extend_flow_coverage
    from src.sources.ttfund_cli import record_attestation
    try:
        result = record_attestation(db, body.covered_from, body.covered_to, body.note)
        result["coverage"] = extend_flow_coverage(db)
        result["sync_log_id"] = _log(db, "ttfund_attestation", json.dumps(
            {"action": "ttfund_attestation", "covered_from": result["covered_from"],
             "covered_to": result["covered_to"], "note": body.note}, ensure_ascii=False))
        mark_dirty()
        return result
    except ValueError as exc:
        return _refused(exc, "ttfund_attestation")
    except Exception as exc:
        logger.exception("TTFund attestation failed")
        return api_error_response(exc, context="ttfund_attestation")
