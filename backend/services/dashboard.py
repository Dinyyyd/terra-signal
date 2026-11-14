"""Turns the provider's four datasets into the unified dashboard payload."""
from __future__ import annotations

import re
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.stats import norm

import config
from data_provider import DataError, get_provider
from ml import stats
from ml.fire_clusters import cluster_fires
from ml.geo import haversine_matrix
from ml.isolation import score_cells
from services import cache

_SECTOR = re.compile(r"\s+Sector\s+\d+$", re.I)
_ctx_memo: tuple[int, dict] | None = None


class LocationNotFound(KeyError):
    pass


class LocationDataUnavailable(LocationNotFound):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def country_location_id(country: str) -> str:
    return slug(f"country {country}")


def area_location_id(country: str, area: str) -> str:
    return slug(f"area {country} {area}")


def region_of(obs: dict) -> str:
    return obs.get("region") or _SECTOR.sub("", obs["name"])


# --------------------------------------------------------------------------- national context
def _context(bundle: dict[str, Any]) -> dict[str, Any]:
    """Everything that is computed once per data refresh, always over the whole country."""
    t = {r["id"]: r for r in bundle["temperature"]["observations"]}
    v = {r["id"]: r for r in bundle["vegetation"]["observations"]}
    p = {r["id"]: r for r in bundle["precipitation"]["observations"]}
    ids = list(t)
    lat = np.array([t[i]["lat"] for i in ids]); lon = np.array([t[i]["lon"] for i in ids])

    fires = bundle["fires"]["detections"]
    fire_available = bundle["fires"].get("source_mode") != "UNAVAILABLE"
    labels = cluster_fires(fires)
    if fires:
        dist = haversine_matrix([f["lat"] for f in fires], [f["lon"] for f in fires], lat, lon)  # fire x cell
        nearest = dist.argmin(axis=1)
        local = (dist <= config.FIRE_LOCAL_RADIUS_KM).sum(axis=0).astype(float)
    else:
        nearest, local = np.array([], int), np.zeros(len(ids))
    mean_local = local.mean()
    d_fire = (local - mean_local) / mean_local * 100 if mean_local > 0 else np.zeros(len(ids))

    z_temp = np.array([stats.z_score(t[i]["current"], t[i]["baseline"], t[i]["sigma"]) for i in ids])
    d_ndvi = np.array([stats.pct_change(v[i]["current_ndvi"], v[i]["baseline_ndvi"]) for i in ids])
    z_rain = norm.ppf(np.clip(np.array([p[i]["percentile"] for i in ids]), 0.5, 99.5) / 100.0)

    matrix = np.column_stack([z_temp, d_ndvi, z_rain, d_fire] if fire_available
                             else [z_temp, d_ndvi, z_rain])
    if bundle["vegetation"].get("unit") == "fraction":
        feature_labels = [
            ("warmer than baseline", "cooler than baseline"),
            ("wetter soil than baseline", "drier soil than baseline"),
            ("wetter than normal", "rainfall deficit"),
        ]
        if fire_available:
            feature_labels.append(("high local fire activity", "little fire activity"))
    else:
        feature_labels = None
    outlier, score, drivers = score_cells(matrix, feature_labels)

    cells = []
    for k, cid in enumerate(ids):
        country = t[cid].get("country")
        if not country:
            location_name = bundle["temperature"].get("location", "")
            if location_name and not location_name.startswith("Global_"):
                country = location_name.replace("_", " ")
        area = t[cid].get("area") or region_of(t[cid])
        if area == country:
            area = None
        country_id = country_location_id(country) if country else None
        area_id = area_location_id(country, area) if country and area else country_id
        region = f"{area}, {country}" if area and country else area or country or region_of(t[cid])
        cells.append({
            "id": cid, "name": t[cid]["name"], "region": region, "country": country,
            "area": area, "country_id": country_id, "area_id": area_id,
            "location_id": area_id or cid,
            "lat": t[cid]["lat"], "lon": t[cid]["lon"],
            "temperature": {"current": t[cid]["current"], "baseline": t[cid]["baseline"],
                            "sigma": t[cid]["sigma"], "z_score": round(float(z_temp[k]), 2)},
            "vegetation": {"ndvi": v[cid]["current_ndvi"], "baseline": v[cid]["baseline_ndvi"],
                           "change_percent": round(float(d_ndvi[k]), 1)},
            "precipitation": {"current_mm": p[cid]["current_mm"], "baseline_mm": p[cid]["baseline_mm"],
                              "percentile": p[cid]["percentile"], "z_score": round(float(z_rain[k]), 2)},
            "fires_nearby": int(local[k]),
            "is_outlier": bool(outlier[k]), "anomaly_score": round(float(score[k]), 3),
            "drivers": drivers[k],
        })
    fire_rows = []
    for k, f in enumerate(fires):
        cell = cells[int(nearest[k])]
        fire_rows.append({**f, "cluster": int(labels[k]), "region": cell["region"],
                          "country_id": cell["country_id"], "location_id": cell["location_id"]})
    return {"cells": cells, "fires": fire_rows, "bundle": bundle, "fire_available": fire_available}


def _get_context() -> dict[str, Any]:
    global _ctx_memo
    bundle = get_provider().get()
    if _ctx_memo is None or _ctx_memo[0] != id(bundle):
        _ctx_memo = (id(bundle), _context(bundle))
    return _ctx_memo[1]


# --------------------------------------------------------------------------- locations
def national_id(bundle) -> str:
    return slug(bundle["temperature"].get("location") or "All_Regions")


def list_locations() -> list[dict]:
    ctx = _get_context()
    cells = ctx["cells"]
    bundle = ctx["bundle"]
    nid = national_id(bundle)
    country_names = bundle.get("countries") or sorted({c["country"] for c in cells if c["country"]})
    if not country_names:
        country_name = bundle["temperature"].get("location", "").replace("_", " ")
        country_names = [country_name] if country_name and not country_name.startswith("Global ") else []

    def center(group):
        return (float(np.mean([c["lat"] for c in group])) if group else None,
                float(np.mean([c["lon"] for c in group])) if group else None)

    global_lat, global_lon = center(cells)
    national_name = "Global" if bundle["temperature"].get("grid_spacing_degrees") \
        else f"All areas ({country_names[0]})" if country_names else nid.replace("_", " ")
    out = [{"id": nid, "name": national_name, "scope": "national",
            "lat": global_lat, "lon": global_lon, "cells": len(cells)}]
    cells_by_country: dict[str, list[dict]] = {}
    cells_by_area: dict[tuple[str, str], list[dict]] = {}
    for cell in cells:
        if cell["country"]:
            cells_by_country.setdefault(cell["country"], []).append(cell)
        if cell["country"] and cell["area"]:
            cells_by_area.setdefault((cell["country"], cell["area"]), []).append(cell)

    for name in sorted(country_names):
        group = cells_by_country.get(name, [])
        lat, lon = center(group)
        out.append({"id": country_location_id(name), "name": name, "display_name": name,
                    "scope": "country",
                    "country": name, "country_id": country_location_id(name),
                    "lat": lat, "lon": lon, "cells": len(group)})

    area_catalog = {
        (item["country"], item["name"]): item
        for item in bundle.get("areas", [])
        if item.get("country") and item.get("name")
    }
    for key in cells_by_area:
        area_catalog.setdefault(key, {"country": key[0], "name": key[1]})
    area_scope = "area" if bundle.get("areas") else "region"
    for (country, name), metadata in sorted(area_catalog.items()):
        group = cells_by_area.get((country, name), [])
        lat, lon = center(group)
        out.append({"id": area_location_id(country, name), "name": name,
                    "display_name": f"{name}, {country}", "scope": area_scope,
                    "country": country, "country_id": country_location_id(country),
                    "type": metadata.get("type"), "lat": lat, "lon": lon, "cells": len(group)})
    return out


def _resolve(ctx, location: str) -> tuple[dict, list[dict], list[dict]]:
    locs = list_locations()
    normalized = slug(location).lower()
    match = next((l for l in locs if l["id"].lower() == normalized), None)
    if match is None:
        aliases = [l for l in locs if l["scope"] in ("area", "region")
                   and slug(l["name"]).lower() == normalized]
        match = aliases[0] if len(aliases) == 1 else None
    if match is None:
        raise LocationNotFound(location)
    if match["scope"] == "national":
        cells, fires = ctx["cells"], ctx["fires"]
    elif match["scope"] == "country":
        cells = [c for c in ctx["cells"] if c["country_id"] == match["id"]]
        fires = [f for f in ctx["fires"] if f["country_id"] == match["id"]]
    else:
        cells = [c for c in ctx["cells"] if c["area_id"] == match["id"]]
        fires = [f for f in ctx["fires"] if f["location_id"] == match["id"]]
    if not cells:
        raise LocationDataUnavailable(match["name"])
    return match, cells, fires


def _location_history(bundle: dict[str, Any], kind: str, cells: list[dict],
                      value_key: str, baseline_key: str) -> list[dict]:
    observations = {row["id"]: row for row in bundle[kind]["observations"]}
    selected = [observations[cell["id"]] for cell in cells if "history" in observations[cell["id"]]]
    if not selected:
        return bundle[kind].get("timeseries", [])
    by_date: dict[str, list[tuple[float, float, float]]] = {}
    for cell in selected:
        lat = math.radians(cell["lat"])
        weight = math.sin(min(math.pi / 2, lat + math.radians(2.5))) - \
                 math.sin(max(-math.pi / 2, lat - math.radians(2.5)))
        for row in cell["history"]:
            by_date.setdefault(row["date"], []).append(
                (row[value_key], row[baseline_key], weight)
            )
    result = []
    for date, rows in sorted(by_date.items()):
        total_weight = sum(row[2] for row in rows)
        result.append({
            "date": date,
            value_key: round(sum(row[0] * row[2] for row in rows) / total_weight, 3),
            baseline_key: round(sum(row[1] * row[2] for row in rows) / total_weight, 3),
        })
    return result


# --------------------------------------------------------------------------- payload
def _build(location: str) -> dict[str, Any]:
    ctx = _get_context()
    bundle = ctx["bundle"]
    loc, cells, fires = _resolve(ctx, location)
    def mean(values, rows=None):
        area = rows or cells
        weights = np.array([
            math.sin(min(math.pi / 2, math.radians(c["lat"] + 2.5))) -
            math.sin(max(-math.pi / 2, math.radians(c["lat"] - 2.5)))
            for c in area
        ])
        return float(np.average(values, weights=weights))

    t_cur = mean([c["temperature"]["current"] for c in cells]); t_base = mean([c["temperature"]["baseline"] for c in cells])
    t_sig = mean([c["temperature"]["sigma"] for c in cells]); t_z = stats.z_score(t_cur, t_base, t_sig)
    n_cur = mean([c["vegetation"]["ndvi"] for c in cells]); n_base = mean([c["vegetation"]["baseline"] for c in cells])
    n_chg = stats.pct_change(n_cur, n_base)
    r_cur = mean([c["precipitation"]["current_mm"] for c in cells]); r_base = mean([c["precipitation"]["baseline_mm"] for c in cells])
    r_pct = mean([c["precipitation"]["percentile"] for c in cells])

    prev = bundle["fires"].get("previous_period_detections", len(ctx["fires"]))
    fire_available = ctx["fire_available"]
    f_chg = stats.pct_change(len(ctx["fires"]), prev) if fire_available else None
    labels = {f["cluster"] for f in fires if f["cluster"] >= 0}

    soil_wetness = bundle["vegetation"].get("unit") == "fraction"
    vegetation_status = (stats.soil_wetness_status(n_chg) if soil_wetness
                         else stats.vegetation_status(n_chg))
    vegetation_decline = vegetation_status == "DRYING" if soil_wetness else vegetation_status == "DECLINE"
    st = {"t": stats.temperature_status(t_z), "v": vegetation_status,
          "r": stats.precipitation_status(r_pct),
          "f": stats.fire_status(f_chg, len(fires)) if fire_available else "UNAVAILABLE"}
    flag_values = [st["t"] in ("MODERATE", "EXTREME"), vegetation_decline,
                   st["r"] == "DEFICIT"]
    if fire_available:
        flag_values.append(st["f"] in ("ELEVATED", "CRITICAL"))
    flags = sum(flag_values)
    outliers = sorted([c for c in cells if c["is_outlier"]], key=lambda c: -c["anomaly_score"])
    is_anomaly = flags >= 2
    severity = "HIGH" if flags >= 3 else "MODERATE" if is_anomaly else "LOW"

    parts = []
    temperature_label = "Temperature"
    vegetation_label = "Vegetation"
    if abs(t_z) >= 1:
        parts.append(f"{temperature_label} is {abs(t_z):.1f} standard deviations {'above' if t_z > 0 else 'below'} baseline")
    vegetation_watch = config.SOIL_WATCH_PCT if soil_wetness else config.NDVI_WATCH_PCT
    if n_chg <= vegetation_watch:
        parts.append(f"{vegetation_label} is down {abs(n_chg):.1f}% against its baseline")
    if r_pct < config.RAIN_DEFICIT_PCTL:
        parts.append(f"rainfall sits at the {r_pct:.0f}th percentile (precipitation deficit)")
    elif r_pct >= config.RAIN_EXTREME_PCTL:
        parts.append(f"rainfall sits at the {r_pct:.0f}th percentile (extreme wet signal)")
    if fire_available and f_chg >= config.FIRE_ELEVATED_PCT and fires:
        parts.append(f"{len(fires)} active fire detections in {len(labels)} spatial clusters, {f_chg:+.0f}% country-wide vs the previous period")
    explanation = ("Compound environmental signal: " + "; ".join(parts) + "." if is_anomaly
                   else ("Single-indicator signal only: " + "; ".join(parts) + "." if parts
                         else "No notable signal in the available indicators."))
    if outliers:
        top = ", ".join(f"{c['name']}" + (f" ({', '.join(c['drivers'])})" if c["drivers"] else "") for c in outliers[:3])
        explanation += f" Isolation Forest flags {len(outliers)} unusual cell{'s' if len(outliers) != 1 else ''}; most unusual: {top}."

    # regional hotspots are always country-wide so the user can jump to them from any view
    by_region: dict[str, list[dict]] = {}
    for c in ctx["cells"]:
        by_region.setdefault(c["region"], []).append(c)
    fire_by_region: dict[str, int] = {}
    for f in ctx["fires"]:
        fire_by_region[f["region"]] = fire_by_region.get(f["region"], 0) + 1
    hotspots = sorted(({
        "id": g[0]["location_id"], "name": r, "cells": len(g), "outlier_cells": sum(c["is_outlier"] for c in g),
        "score": round(float(np.mean([c["anomaly_score"] for c in g])), 3),
        "temperature_z": round(mean([c["temperature"]["z_score"] for c in g], g), 2),
        "ndvi_change": round(mean([c["vegetation"]["change_percent"] for c in g], g), 1),
        "rain_percentile": round(mean([c["precipitation"]["percentile"] for c in g], g), 1),
        "fires": fire_by_region.get(r, 0) if fire_available else None} for r, g in by_region.items()),
        key=lambda h: (-h["outlier_cells"], -h["score"]))[:8]

    sources = []
    for kind, label in (("temperature", "Temperature"), ("vegetation", "Vegetation"),
                        ("precipitation", "Precipitation"), ("fires", "Fire detection")):
        ds = bundle[kind]
        sources.append({"indicator": label, "dataset": ds.get("dataset", kind), "source_mode": ds.get("source_mode", "UNKNOWN"),
                        "baseline_period": ds.get("baseline_period", ""), "retrieved_at": ds.get("retrieved_at"),
                        "fallback_reason": ds.get("fallback_reason"),
                        "records": len(ds.get("observations") or ds.get("detections") or [])})
    modes = {s["source_mode"].upper().split(" ")[0] for s in sources}
    if "ARCHIVE" in modes and modes <= {"ARCHIVE", "UNAVAILABLE"}:
        source_mode = "ARCHIVE"
    else:
        source_mode = "LIVE" if modes == {"LIVE"} else "MOCK" if "LIVE" not in modes else "MIXED"

    dates = [r["date"] for r in bundle["temperature"].get("timeseries", [])] or \
            [r.get("date") for r in bundle["temperature"]["observations"] if r.get("date")]
    temperature_timeseries = _location_history(bundle, "temperature", cells, "current", "baseline")
    vegetation_timeseries = _location_history(
        bundle, "vegetation", cells, "current_ndvi", "baseline_ndvi"
    )
    precipitation_timeseries = _location_history(
        bundle, "precipitation", cells, "current_mm", "baseline_mm"
    )
    now = datetime.now(timezone.utc).isoformat()
    return {
        "location": loc["id"], "location_name": loc.get("display_name", loc["name"]), "scope": loc["scope"],
        "center": {"lat": loc["lat"], "lon": loc["lon"]},
        "generated_at": now, "served_from_cache": False,
        "source_mode": source_mode, "sources": sources,
        "observation_window": {"start": min(dates) if dates else None, "end": max(dates) if dates else None},
        "overall_anomaly": {"is_anomaly": is_anomaly, "severity": severity, "rule_flags": int(flags),
                            "isolation_forest_anomaly_points": len(outliers), "cells_analysed": len(cells)},
        "temperature": {"current": round(t_cur, 2), "baseline": round(t_base, 2), "z_score": round(t_z, 2),
                        "status": st["t"], "unit": bundle["temperature"].get("unit", "°C"),
                        "label": "Temperature",
                        "timeseries": temperature_timeseries},
        "vegetation": {"ndvi": round(n_cur, 3), "baseline": round(n_base, 3), "change_percent": round(n_chg, 1),
                       "status": st["v"], "unit": bundle["vegetation"].get("unit", "NDVI"),
                       "label": "Vegetation",
                       "timeseries": vegetation_timeseries},
        "precipitation": {"current_mm": round(r_cur, 1), "baseline_mm": round(r_base, 1), "percentile": round(r_pct, 1),
                          "status": st["r"], "unit": bundle["precipitation"].get("unit", "mm/day"),
                          "label": "Precipitation",
                          "timeseries": precipitation_timeseries},
        "fire": {"detections": len(fires), "previous_period_detections": prev, "clusters": len(labels),
                 "change_percent": round(f_chg, 1) if fire_available else None,
                 "change_scope": "national", "status": st["f"],
                 "available": fire_available, "detections_detail": fires},
        "timeseries_scope": "location" if bundle["temperature"].get("grid_spacing_degrees") else "national",
        "grid_spacing_degrees": bundle["temperature"].get("grid_spacing_degrees"),
        "cells": cells, "hotspots": hotspots, "explanation": explanation,
        "methodology": {
            "temperature": f"Z = (x − μ) / σ; |Z| ≥ {config.Z_EXTREME:g} extreme, {config.Z_MODERATE:g}–{config.Z_EXTREME:g} moderate.",
            "vegetation": (f"Root-zone soil wetness fraction; decreases ≤ {config.SOIL_DRYING_PCT:g}% are drying and "
                           f"≤ {config.SOIL_WATCH_PCT:g}% are a watch signal against the same-month baseline."
                           if soil_wetness else
                           f"{bundle['vegetation'].get('label', 'NDVI')} value and change against the same-month baseline; "
                           f"≤ {config.NDVI_DECLINE_PCT:g}% decline, ≤ {config.NDVI_WATCH_PCT:g}% watch."),
            "precipitation": f"Historical distribution quantile rank (percentile position); < {config.RAIN_DEFICIT_PCTL:g}th = deficit, ≥ {config.RAIN_EXTREME_PCTL:g}th = extreme.",
            "fire": (f"DBSCAN (haversine) eps = {config.DBSCAN_EPS_KM:g} km, min_samples = {config.DBSCAN_MIN_SAMPLES}; no preset cluster count."
                     if fire_available else "Historical fire observations are unavailable in this archive."),
            "compound": (f"Isolation Forest over standardised {temperature_label}, {vegetation_label}, and precipitation indicators per grid cell; "
                         "historical fire data are unavailable and excluded." if not fire_available else
                         "Isolation Forest over standardised V = [Z_temp, Δ%NDVI, Z_rain, Δ%Fire_local] per grid cell; ")
                        +
                        f"top {config.IFOREST_CONTAMINATION:.0%} most isolated cells are flagged. A compound anomaly needs ≥ 2 indicator flags.",
        },
    }


def get_dashboard(location: str) -> dict[str, Any]:
    """Fresh payload when possible; otherwise the last cached payload (fail-safe demo mode)."""
    try:
        payload = _build(location)
    except LocationNotFound:
        raise
    except Exception as exc:  # noqa: BLE001
        cached = cache.load(slug(location))
        if cached is None:
            raise
        payload = cached["payload"]
        payload["served_from_cache"] = True
        payload["cache_warning"] = f"Live data unavailable ({type(exc).__name__}); showing cached data from {cached['updated_at']}."
        return payload
    cache.save(payload["location"], payload)
    return payload


def reset_memo() -> None:
    global _ctx_memo
    _ctx_memo = None
