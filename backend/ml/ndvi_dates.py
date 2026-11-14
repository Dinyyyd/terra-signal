"""Pixel acquisition dates for the December MOD13Q1 pilot validation."""
import calendar
from datetime import date
import numpy as np


def december_acquisition_dates(composite_start, doy, valid):
    start = date.fromisoformat(composite_start)
    if start.month != 12 or start.day not in (3, 19) or calendar.isleap(start.year):
        raise ValueError("This pilot decoder supports non-leap-year December 3/19 only")
    doy, valid = np.asarray(doy), np.asarray(valid, dtype=bool)
    if doy.shape != valid.shape:
        raise ValueError("DOY and validity grids differ")
    first = start.timetuple().tm_yday
    same = valid & (doy >= first) & (doy <= min(first + 15, 365))
    rollover = valid & (start.day == 19) & (doy >= 1) & (doy <= 8)
    if np.any(valid & (~(same | rollover) | (doy != np.floor(doy)))):
        raise ValueError("Unresolved acquisition DOY; inspect source metadata")
    result = np.full(doy.shape, np.datetime64("NaT"), dtype="datetime64[D]")
    for mask, year in ((same, start.year), (rollover, start.year + 1)):
        result[mask] = np.datetime64(f"{year}-01-01") + (doy[mask] - 1).astype("timedelta64[D]")
    return result
