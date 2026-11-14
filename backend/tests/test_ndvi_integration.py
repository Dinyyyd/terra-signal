import json
import numpy as np
import pytest
from fastapi import HTTPException
from ml.ndvi_dates import december_acquisition_dates
from routers.ndvi import canberra_candidate


def test_rollover():
    dates = december_acquisition_dates("2025-12-19", np.array([353, 3, -1]), np.array([True, True, False]))
    assert str(dates[0]) == "2025-12-19"
    assert str(dates[1]) == "2026-01-03"
    assert np.isnat(dates[2])
    with pytest.raises(ValueError):
        december_acquisition_dates("2025-12-03", np.array([3]), np.array([True]))


def test_review_disabled(monkeypatch):
    monkeypatch.delenv("SATSCOPE_NDVI_REVIEW_DIR", raising=False)
    with pytest.raises(HTTPException) as error:
        canberra_candidate()
    assert error.value.status_code == 503


def test_review_preserves_missing_data(tmp_path, monkeypatch):
    payload = dict(deployment_allowed=False, date="2025-12-19", status="INSUFFICIENT_COVERAGE",
                   reportable=False, matched_coverage_percent=40, current=0.4,
                   composite_end="2025-12-31")
    (tmp_path / "candidate_latest.json").write_text(json.dumps(payload))
    monkeypatch.setenv("SATSCOPE_NDVI_REVIEW_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as error:
        canberra_candidate()
    assert error.value.status_code == 503  # A standalone summary is no longer enough.
