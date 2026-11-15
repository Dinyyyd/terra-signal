"""Real NASA POWER historical archive provider; no simulated fallback."""
from __future__ import annotations

import json
import math
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import config

KINDS = ("temperature", "vegetation", "precipitation", "fires")
_REQUIRED = {
    "temperature": ("id", "name", "lat", "lon", "current", "baseline", "sigma"),
    "vegetation": ("id", "name", "lat", "lon", "current_ndvi", "baseline_ndvi"),
    "precipitation": ("id", "name", "lat", "lon", "current_mm", "baseline_mm", "percentile"),
}
_TS_REQUIRED = {"temperature": ("date", "current", "baseline"),
                "vegetation": ("date", "current_ndvi", "baseline_ndvi"),
                "precipitation": ("date", "current_mm", "baseline_mm")}


class DataError(ValueError):
    """Raised when a provider returns data that does not match the contract."""


def validate(kind: str, ds: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ds, dict):
        raise DataError(f"{kind}: expected an object, got {type(ds).__name__}")
    if kind == "fires":
        dets = ds.get("detections")
        if not isinstance(dets, list):
            raise DataError("fires: 'detections' must be a list")
        for i, d in enumerate(dets):
            for k in ("lat", "lon"):
                if not isinstance(d.get(k), (int, float)):
                    raise DataError(f"fires.detections[{i}]: missing numeric '{k}'")
        ds.setdefault("previous_period_detections", len(dets))
        return ds
    obs = ds.get("observations")
    if not isinstance(obs, list) or not obs:
        raise DataError(f"{kind}: 'observations' must be a non-empty list")
    for i, row in enumerate(obs):
        for k in _REQUIRED[kind]:
            if k not in row or row[k] is None:
                raise DataError(f"{kind}.observations[{i}]: missing field '{k}'")
            if k not in ("id", "name") and not isinstance(row[k], (int, float)):
                raise DataError(f"{kind}.observations[{i}]: '{k}' must be numeric")
    ts = ds.setdefault("timeseries", [])
    for i, row in enumerate(ts):
        for k in _TS_REQUIRED[kind]:
            if k not in row:
                raise DataError(f"{kind}.timeseries[{i}]: missing field '{k}'")
    return ds


def validate_all(bundle: dict[str, Any]) -> dict[str, Any]:
    for kind in KINDS:
        if kind not in bundle:
            raise DataError(f"provider did not return '{kind}'")
        validate(kind, bundle[kind])
    ids = [set(r["id"] for r in bundle[k]["observations"]) for k in KINDS[:3]]
    if not (ids[0] == ids[1] == ids[2]):
        raise DataError("temperature, vegetation and precipitation must contain the same cell ids")
    return bundle


class DataProvider:
    mode = "base"

    def get(self) -> dict[str, Any]:           # cached, validated bundle
        raise NotImplementedError

    def refresh(self) -> None:                 # drop caches so the next get() re-reads
        pass


# --------------------------------------------------------------------------- global NASA archive
def _area_weight(lat: float) -> float:
    top = math.radians(min(90.0, lat + 2.5))
    bottom = math.radians(max(-90.0, lat - 2.5))
    return math.sin(top) - math.sin(bottom)


def _weighted_history(cells: list[dict], value_key: str, baseline_key: str) -> list[dict]:
    by_date: dict[str, list[tuple[float, float, float]]] = {}
    for cell in cells:
        weight = _area_weight(cell["lat"])
        for row in cell["history"]:
            by_date.setdefault(row["date"], []).append(
                (row[value_key], row[baseline_key], weight)
            )
    out = []
    for d, rows in sorted(by_date.items()):
        total_weight = sum(row[2] for row in rows)
        out.append({
            "date": d,
            value_key: round(sum(row[0] * row[2] for row in rows) / total_weight, 3),
            baseline_key: round(sum(row[1] * row[2] for row in rows) / total_weight, 3),
        })
    return out


class GlobalPowerArchiveProvider(DataProvider):
    """Reads bundled monthly NASA POWER data sampled at global 5-degree cell centers."""
    mode = "archive"

    def __init__(self, path: Path = config.GLOBAL_HISTORY_FILE):
        self.path = path
        self._signature = None
        self._bundle = None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            try:
                signature = self.path.stat().st_mtime_ns
            except FileNotFoundError:
                raise DataError(f"Missing NASA history archive: {self.path}")
            if self._bundle is None or signature != self._signature:
                self._bundle = self._read()
                self._signature = signature
            return self._bundle

    def refresh(self):
        with self._lock:
            self._bundle = None

    def _read(self):
        try:
            archive = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise DataError(f"Missing NASA history archive: {self.path}")
        except json.JSONDecodeError as e:
            raise DataError(f"NASA history archive is not valid JSON: {e}")

        baseline_years = set(archive.get("baseline_years", []))
        cells = archive.get("cells")
        if not isinstance(cells, list) or not cells:
            raise DataError("NASA history archive must contain grid cells")
        if not baseline_years:
            raise DataError("NASA history archive is missing its baseline years")

        temperature_obs, vegetation_obs, precipitation_obs = [], [], []
        for cell in cells:
            series = cell.get("series")
            if not isinstance(series, list) or not series:
                raise DataError(f"{cell.get('id', 'unknown cell')}: missing monthly series")
            latest = series[-1]
            month = int(latest["date"][5:7])
            climatology = [row for row in series
                           if int(row["date"][:4]) in baseline_years
                           and int(row["date"][5:7]) == month]
            if not climatology:
                raise DataError(f"{cell['id']}: no baseline data for month {month}")

            def baseline(variable):
                return statistics.fmean(row[variable] for row in climatology)

            t_base = baseline("temperature_c")
            t_values = [row["temperature_c"] for row in climatology]
            p_base = baseline("precipitation_mm_day")
            p_values = [row["precipitation_mm_day"] for row in climatology]
            w_base = baseline("root_zone_soil_wetness")
            w_values = [row["root_zone_soil_wetness"] for row in climatology]
            temp_history, rain_history, wet_history = [], [], []
            by_month: dict[int, list[dict]] = {}
            for row in series:
                by_month.setdefault(int(row["date"][5:7]), []).append(row)
            for row in series:
                m = int(row["date"][5:7])
                prior = [r for r in by_month[m] if int(r["date"][:4]) in baseline_years]
                t_clim = statistics.fmean(r["temperature_c"] for r in prior)
                p_clim = statistics.fmean(r["precipitation_mm_day"] for r in prior)
                w_clim = statistics.fmean(r["root_zone_soil_wetness"] for r in prior)
                d = row["date"] + "-01"
                temp_history.append({"date": d, "current": row["temperature_c"], "baseline": t_clim})
                rain_history.append({"date": d, "current_mm": row["precipitation_mm_day"],
                                     "baseline_mm": p_clim})
                wet_history.append({"date": d, "current_ndvi": row["root_zone_soil_wetness"],
                                    "baseline_ndvi": w_clim})

            country = cell.get("country")
            area = cell.get("area")
            region = f"{area}, {country}" if area and country else country or cell["name"]
            common = {"id": cell["id"], "name": cell["name"], "lat": cell["lat"],
                      "lon": cell["lon"], "region": region, "country": country,
                      "area": area, "date": latest["date"] + "-01"}
            temperature_obs.append({
                **common, "current": latest["temperature_c"], "baseline": t_base,
                "sigma": statistics.pstdev(t_values) or 0.5, "history": temp_history,
            })
            vegetation_obs.append({
                **common, "current_ndvi": latest["root_zone_soil_wetness"],
                "baseline_ndvi": w_base, "history": wet_history,
            })
            below = sum(value < latest["precipitation_mm_day"] for value in p_values)
            tied = sum(value == latest["precipitation_mm_day"] for value in p_values)
            precipitation_obs.append({
                **common, "current_mm": latest["precipitation_mm_day"], "baseline_mm": p_base,
                "percentile": 100 * (below + 0.5 * tied) / len(p_values),
                "history": rain_history,
            })

        temperature_history = _weighted_history(temperature_obs, "current", "baseline")
        vegetation_history = _weighted_history(vegetation_obs, "current_ndvi", "baseline_ndvi")
        precipitation_history = _weighted_history(precipitation_obs, "current_mm", "baseline_mm")
        baseline_label = f"Same-month climatology, {min(baseline_years)}–{max(baseline_years)}"
        source_mode = "ARCHIVE"
        bundle = {
            "temperature": {
                "dataset": "NASA POWER T2M monthly (MERRA-2)", "label": "2 m air temperature",
                "source_mode": source_mode, "location": "Global_5deg", "unit": "°C",
                "baseline_period": baseline_label, "grid_spacing_degrees": 5,
                "observations": temperature_obs, "timeseries": temperature_history,
            },
            "vegetation": {
                "dataset": "NASA POWER GWETROOT monthly (MERRA-2)",
                "label": "Root-zone soil wetness", "source_mode": source_mode,
                "location": "Global_5deg", "unit": "fraction",
                "baseline_period": baseline_label, "grid_spacing_degrees": 5,
                "observations": vegetation_obs, "timeseries": vegetation_history,
            },
            "precipitation": {
                "dataset": "NASA POWER PRECTOTCORR monthly (MERRA-2)",
                "label": "Precipitation", "source_mode": source_mode,
                "location": "Global_5deg", "unit": "mm/day",
                "baseline_period": baseline_label, "grid_spacing_degrees": 5,
                "observations": precipitation_obs, "timeseries": precipitation_history,
            },
            "fires": {
                "dataset": "Historical fire archive not included",
                "source_mode": "UNAVAILABLE", "location": "Global_5deg",
                "previous_period_detections": 0, "detections": [],
                "baseline_period": "No historical fire data in NASA POWER",
            },
            "countries": archive.get("countries", []),
            "areas": archive.get("areas", []),
        }
        return validate_all(bundle)


# --------------------------------------------------------------------------- registry
PROVIDERS: dict[str, Callable[[], DataProvider]] = {
    "archive": GlobalPowerArchiveProvider,
}
_instance: DataProvider | None = None


def get_provider() -> DataProvider:
    global _instance
    if _instance is None:
        factory = PROVIDERS.get(config.DATA_SOURCE)
        if factory is None:
            raise DataError(f"Unknown DATA_SOURCE '{config.DATA_SOURCE}'. Options: {', '.join(PROVIDERS)}")
        _instance = factory()
    return _instance
