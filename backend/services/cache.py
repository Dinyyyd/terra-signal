"""SQLite cache of the last good dashboard payload per location (historical archive only)."""
import json

from services.security import db


def save(location: str, payload: dict) -> None:
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO dashboard_cache(location,payload,updated_at) VALUES(?,?,?)",
                     (location, json.dumps(payload), payload["generated_at"]))


def load(location: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT payload, updated_at FROM dashboard_cache WHERE location=?",
                           (location,)).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload"])
    if payload.get("source_mode") != "ARCHIVE":
        return None
    return {"updated_at": row["updated_at"], "payload": payload}
