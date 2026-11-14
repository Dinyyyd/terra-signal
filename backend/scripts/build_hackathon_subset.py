"""Build a small, reproducible archive without altering source observations."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNTRIES = ["Sri Lanka", "United States of America", "United Kingdom", "Australia", "India"]


def build():
    source = ROOT / "data/history/nasa_power_global_monthly_2011_2025.json"
    target = ROOT / "data/history/hackathon_five_countries.json"
    raw = source.read_bytes()
    archive = json.loads(raw)
    archive["cells"] = [c for c in archive["cells"] if c.get("country") in COUNTRIES]
    archive["countries"] = COUNTRIES
    archive["areas"] = [a for a in archive["areas"] if a.get("country") in COUNTRIES]
    archive["cell_count"] = len(archive["cells"])
    archive["title"] = "Five-country historical hackathon pilot"
    archive["display_name"] = "Pilot countries"
    archive["subset_provenance"] = {
        "source_file": source.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "method": "Country filter only; original series and baseline years preserved",
        "real_time": False,
        "missing_countries": [c for c in COUNTRIES if not any(x["country"] == c for x in archive["cells"])],
    }
    target.write_text(json.dumps(archive, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {target}: {len(archive['cells'])} cells, {target.stat().st_size:,} bytes")
    print("Countries without observations:", archive["subset_provenance"]["missing_countries"])


if __name__ == "__main__":
    build()
