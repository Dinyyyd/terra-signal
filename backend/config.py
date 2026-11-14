"""Central configuration. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MOCK_DIR = DATA_DIR / "mock"
GRID_FILE = DATA_DIR / "region_grid.json"
GLOBAL_HISTORY_FILE = Path(os.getenv(
    "SATSCOPE_HISTORY_FILE", DATA_DIR / "history" / "hackathon_five_countries.json"))
DB_PATH = Path(os.getenv("SATSCOPE_DB", DATA_DIR / "sat_scope.sqlite"))

# "mock"  -> read the four JSON files in data/mock/
# "live"  -> call NASA services (see backend/data_provider.py)
# "archive" -> read the bundled global NASA POWER history
DATA_SOURCE = os.getenv("DATA_SOURCE", "archive").lower()

AUTHOR = {"name": "Sarujan Puvirajan", "email": "saru.contacts@gmail.com"}
DEFAULT_USERNAME = "sarujan"
DEFAULT_PASSWORD = "password"
MIN_PASSWORD_LENGTH = 8
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 300

CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

# Live-provider settings
NASA_FIRMS_MAP_KEY = os.getenv("NASA_FIRMS_MAP_KEY", "")
LIVE_CACHE_MINUTES = int(os.getenv("LIVE_CACHE_MINUTES", "60"))

# Analytics thresholds (kept here so the methodology text stays truthful)
Z_MODERATE, Z_EXTREME = 2.0, 3.0
NDVI_WATCH_PCT, NDVI_DECLINE_PCT = -5.0, -15.0
SOIL_WATCH_PCT, SOIL_DRYING_PCT = -5.0, -15.0
RAIN_DEFICIT_PCTL, RAIN_EXTREME_PCTL = 20.0, 95.0
FIRE_ELEVATED_PCT, FIRE_CRITICAL_PCT = 25.0, 100.0
DBSCAN_EPS_KM = float(os.getenv("DBSCAN_EPS_KM", "15"))
DBSCAN_MIN_SAMPLES = int(os.getenv("DBSCAN_MIN_SAMPLES", "3"))
FIRE_LOCAL_RADIUS_KM = 25.0
IFOREST_CONTAMINATION = 0.08
IFOREST_MIN_CELLS = 10
