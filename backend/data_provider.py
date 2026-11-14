"""
SAT-SCOPE data provider  -  THE ONE FILE YOU CHANGE to move from mock to real NASA data.
=========================================================================================

The rest of the application (analytics, API, dashboard) only ever calls
`get_provider().get()` and receives four dictionaries with the schemas below.
As long as your data source returns these shapes, nothing else needs to change.

    temperature   {"dataset", "source_mode", "unit", "baseline_period",
                   "observations": [{"id","name","lat","lon","current","baseline","sigma","date"}],
                   "timeseries":   [{"date","current","baseline"}]}
    vegetation    observations: {"id","name","lat","lon","current_ndvi","baseline_ndvi","date"}
                  timeseries:   {"date","current_ndvi","baseline_ndvi"}
    precipitation observations: {"id","name","lat","lon","current_mm","baseline_mm","percentile","date"}
                  timeseries:   {"date","current_mm","baseline_mm"}
    fires         {"dataset","source_mode","previous_period_detections",
                   "detections": [{"id","lat","lon","brightness","confidence","acq_date","acq_time","frp"}]}

`id` must match across temperature / vegetation / precipitation (one id per grid cell).
Set `source_mode` to "LIVE" for real data; the UI badge switches automatically.

Three ways to switch:
  1. Keep the JSON files but overwrite them with real exports      (DATA_SOURCE=mock)
  2. Use the built-in NASA adapters below                          (DATA_SOURCE=live)
  3. Write your own class (e.g. a database / raster pipeline) and register it in PROVIDERS.
"""
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
_MOCK_FILES = {"temperature": "temperature.json", "vegetation": "vegetation.json",
               "precipitation": "precipitation.json", "fires": "fires.json"}

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


# --------------------------------------------------------------------------- mock
class MockJsonProvider(DataProvider):
    """Reads the four JSON files. Edits to the files are picked up automatically (mtime check)."""
    mode = "mock"

    def __init__(self, folder: Path = config.MOCK_DIR):
        self.folder, self._sig, self._bundle = folder, None, None
        self._lock = threading.Lock()

    def _signature(self):
        return tuple((self.folder / f).stat().st_mtime_ns for f in _MOCK_FILES.values())

    def _read(self):
        out = {}
        for kind, fname in _MOCK_FILES.items():
            path = self.folder / fname
            try:
                out[kind] = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise DataError(f"Missing dataset file: {path}")
            except json.JSONDecodeError as e:
                raise DataError(f"{fname} is not valid JSON: {e}")
        return validate_all(out)

    def get(self):
        with self._lock:
            sig = self._signature()
            if self._bundle is None or sig != self._sig:
                self._bundle, self._sig = self._read(), sig
            return self._bundle

    def refresh(self):
        with self._lock:
            self._bundle = None


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


# --------------------------------------------------------------------------- live NASA
def _http(url: str, timeout: int = 40, retries: int = 2) -> str:
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SAT-SCOPE/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise DataError(f"request failed: {url.split('?')[0]} ({last})")


def _grid() -> list[dict]:
    return json.loads(config.GRID_FILE.read_text(encoding="utf-8"))["cells"]


class LiveNasaProvider(DataProvider):
    """
    Live adapters. Each indicator is independent; if one fails, THAT indicator falls back
    to the mock file and is labelled "MOCK (fallback)" in the UI, so the app never goes down.

      fires         NASA FIRMS area API, VIIRS_SNPP_NRT      needs NASA_FIRMS_MAP_KEY (free)
      temperature   NASA POWER daily point API, TS (earth skin temperature, MERRA-2 based)
      precipitation NASA POWER daily point API, PRECTOTCORR (IMERG-corrected precipitation)
      vegetation    hook only - plug your MODIS NDVI source into `_live_vegetation`

    NOTE: POWER 'TS' is a reanalysis skin temperature, not MODIS LST. Swap `_live_temperature`
    for a MODIS MOD11 pipeline (Earthdata login) when you have one. Baselines here are the
    trailing 60-day mean/std for each cell, not a multi-year seasonal climatology.
    """
    mode = "live"
    WINDOW_DAYS = 60

    def __init__(self):
        self._mock = MockJsonProvider()
        self._bundle, self._at = None, 0.0
        self._lock = threading.Lock()

    def refresh(self):
        with self._lock:
            self._bundle = None

    def get(self):
        with self._lock:
            if self._bundle and time.time() - self._at < config.LIVE_CACHE_MINUTES * 60:
                return self._bundle
            self._bundle, self._at = self._build(), time.time()
            return self._bundle

    def _build(self):
        mock = self._mock.get()
        power: dict | None = None
        builders: dict[str, Callable[[], dict]] = {}

        def get_power():
            nonlocal power
            if power is None:
                power = self._fetch_power()
            return power

        builders["temperature"] = lambda: self._live_temperature(get_power())
        builders["precipitation"] = lambda: self._live_precipitation(get_power())
        builders["vegetation"] = self._live_vegetation
        builders["fires"] = self._live_fires
        out = {}
        for kind in KINDS:
            try:
                ds = validate(kind, builders[kind]())
                ds["source_mode"] = "LIVE"
                ds["retrieved_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as e:  # noqa: BLE001 - deliberate: any failure degrades to mock
                ds = json.loads(json.dumps(mock[kind]))
                ds["source_mode"] = "MOCK (fallback)"
                ds["fallback_reason"] = f"{type(e).__name__}: {e}"[:300]
            out[kind] = ds
        # Cells must line up; if live cells diverge from the mock grid, re-align on the live ones.
        return validate_all(out) if self._cells_match(out) else self._all_mock_fallback(mock, out)

    @staticmethod
    def _cells_match(out):
        ids = [set(r["id"] for r in out[k]["observations"]) for k in KINDS[:3]]
        return ids[0] == ids[1] == ids[2]

    @staticmethod
    def _all_mock_fallback(mock, out):
        for k in KINDS[:3]:
            if out[k]["source_mode"] == "LIVE":
                out[k] = json.loads(json.dumps(mock[k]))
                out[k]["source_mode"] = "MOCK (fallback)"
                out[k]["fallback_reason"] = "Cell ids differ between indicators"
        return out

    # ---- NASA POWER (temperature + precipitation) --------------------------------
    def _fetch_power(self) -> dict[str, dict]:
        end = date.today() - timedelta(days=3)      # POWER publishes with a few days' latency
        start = end - timedelta(days=self.WINDOW_DAYS - 1)

        def one(cell):
            url = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=TS,PRECTOTCORR"
                   f"&community=AG&longitude={cell['lon']}&latitude={cell['lat']}"
                   f"&start={start:%Y%m%d}&end={end:%Y%m%d}&format=JSON")
            p = json.loads(_http(url))["properties"]["parameter"]
            return cell, p

        with ThreadPoolExecutor(max_workers=8) as pool:
            return {c["id"]: (c, p) for c, p in pool.map(one, _grid())}

    @staticmethod
    def _series(p: dict, key: str) -> list[tuple[str, float]]:
        return [(d, v) for d, v in sorted(p[key].items()) if v is not None and v > -900]

    def _summarise(self, power, key):
        rows, per_date = [], {}
        for cid, (cell, p) in power.items():
            s = self._series(p, key)
            if len(s) < 15:
                continue
            *hist, (d_now, v_now) = s
            base = [v for _, v in hist[:-7]] or [v for _, v in hist]
            rows.append({"cell": cell, "date": d_now, "now": v_now, "base": base, "series": s})
            for d, v in s[-8:]:
                per_date.setdefault(d, []).append((v, statistics.fmean(base)))
        if not rows:
            raise DataError(f"no valid {key} values returned")
        ts = [(d, statistics.fmean(v for v, _ in vals), statistics.fmean(b for _, b in vals))
              for d, vals in sorted(per_date.items())]
        return rows, ts

    @staticmethod
    def _iso(d: str) -> str:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"

    def _live_temperature(self, power):
        rows, ts = self._summarise(power, "TS")
        obs = [{"id": r["cell"]["id"], "name": r["cell"]["name"], "lat": r["cell"]["lat"],
                "lon": r["cell"]["lon"], "current": round(r["now"], 2),
                "baseline": round(statistics.fmean(r["base"]), 2),
                "sigma": round(statistics.pstdev(r["base"]) or 0.5, 2), "date": self._iso(r["date"])}
                for r in rows]
        return {"dataset": "NASA POWER Earth Skin Temperature (TS)", "unit": "°C",
                "baseline_period": f"Trailing {self.WINDOW_DAYS}-day mean per cell", "observations": obs,
                "timeseries": [{"date": self._iso(d), "current": round(v, 2), "baseline": round(b, 2)}
                               for d, v, b in ts]}

    def _live_precipitation(self, power):
        rows, ts = self._summarise(power, "PRECTOTCORR")
        obs = []
        for r in rows:
            below = sum(1 for v in r["base"] if v < r["now"]) + 0.5 * sum(1 for v in r["base"] if v == r["now"])
            obs.append({"id": r["cell"]["id"], "name": r["cell"]["name"], "lat": r["cell"]["lat"],
                        "lon": r["cell"]["lon"], "current_mm": round(r["now"], 2),
                        "baseline_mm": round(statistics.fmean(r["base"]), 2),
                        "percentile": round(100 * below / len(r["base"]), 1), "date": self._iso(r["date"])})
        return {"dataset": "NASA POWER PRECTOTCORR (IMERG-corrected)", "unit": "mm/day",
                "baseline_period": f"Trailing {self.WINDOW_DAYS}-day distribution per cell",
                "observations": obs,
                "timeseries": [{"date": self._iso(d), "current_mm": round(v, 2), "baseline_mm": round(b, 2)}
                               for d, v, b in ts]}

    # ---- NASA FIRMS ---------------------------------------------------------------
    def _live_fires(self):
        if not config.NASA_FIRMS_MAP_KEY:
            raise DataError("NASA_FIRMS_MAP_KEY is not set (free key: firms.modaps.eosdis.nasa.gov/api/map_key)")
        cells = _grid()
        lats, lons = [c["lat"] for c in cells], [c["lon"] for c in cells]
        pad = 0.3
        bbox = f"{min(lons)-pad:.3f},{min(lats)-pad:.3f},{max(lons)+pad:.3f},{max(lats)+pad:.3f}"
        base = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{config.NASA_FIRMS_MAP_KEY}/VIIRS_SNPP_NRT/{bbox}"
        today = date.today()
        now_rows = self._csv(_http(f"{base}/5/{today:%Y-%m-%d}"))
        prev_rows = self._csv(_http(f"{base}/5/{today - timedelta(days=5):%Y-%m-%d}"))
        conf = {"l": "low", "n": "nominal", "h": "high"}
        dets = [{"id": f"FIR-{i+1:04d}", "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                 "brightness": float(r.get("bright_ti4") or 0), "confidence": conf.get(r.get("confidence", ""), r.get("confidence", "")),
                 "acq_date": r.get("acq_date", ""), "acq_time": f"{str(r.get('acq_time','0000')).zfill(4)[:2]}:{str(r.get('acq_time','0000')).zfill(4)[2:]}",
                 "frp": float(r.get("frp") or 0)} for i, r in enumerate(now_rows)]
        return {"dataset": "NASA FIRMS VIIRS S-NPP NRT active fires", "unit": "detections",
                "baseline_period": "Previous 5-day window", "previous_period_detections": len(prev_rows),
                "detections": dets}

    @staticmethod
    def _csv(text: str) -> list[dict]:
        import csv, io
        if text.lstrip().lower().startswith(("invalid", "error")):
            raise DataError(text.strip()[:200])
        return list(csv.DictReader(io.StringIO(text)))

    # ---- MODIS NDVI hook ----------------------------------------------------------
    def _live_vegetation(self):
        """
        Plug your MODIS NDVI source here (e.g. MOD13Q1 via Earthdata / AppEEARS / GIBS-derived).
        Return the `vegetation` schema from the module docstring. Until then this indicator
        transparently falls back to data/mock/vegetation.json.
        """
        raise NotImplementedError("MODIS NDVI adapter not configured yet")


# --------------------------------------------------------------------------- registry
PROVIDERS: dict[str, Callable[[], DataProvider]] = {
    "archive": GlobalPowerArchiveProvider,
    "mock": MockJsonProvider,
    "live": LiveNasaProvider,
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
