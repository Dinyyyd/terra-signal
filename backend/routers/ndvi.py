"""Opt-in local candidate review; separate from compound dashboard analytics."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from routers.auth import current_user

router = APIRouter(prefix="/api/ndvi", tags=["NDVI candidate"], dependencies=[Depends(current_user)])


@router.get("/canberra")
def canberra_candidate():
    folder = os.getenv("SATSCOPE_NDVI_REVIEW_DIR")
    if not folder:
        raise HTTPException(503, "NDVI candidate review is disabled; no observed dataset configured.")
    try:
        payload = json.loads((Path(folder) / "candidate_latest.json").read_text(encoding="utf-8"))
        if payload.get("deployment_allowed") is not False:
            raise ValueError("Expected an offline candidate")
        if not all(k in payload for k in ("date", "status", "reportable", "matched_coverage_percent")):
            raise ValueError("Incomplete candidate metadata")
        if payload["reportable"]:
            if not all(isinstance(payload.get(k), (int, float)) for k in ("current", "baseline", "change_percent")):
                raise ValueError("Missing reportable values")
        else:
            for k in ("current", "baseline", "absolute_difference", "change_percent"):
                payload[k] = None
        # Historical exports used this as a calendar label, not an acquisition bound.
        payload.pop("composite_end", None)
        return {"study_area": "Canberra pilot", "country": "Australia",
                "indicator": "NDVI", "source": "MOD13Q1.061",
                "mode": "OFFLINE_CANDIDATE_REVIEW", "compound_eligible": False,
                "temporal_note": "Composite start label; pixels may include early next-year acquisitions.",
                "result": payload}
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(503, "NDVI candidate unavailable or invalid") from exc
