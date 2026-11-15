import gzip
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

TMP = Path(__file__).parent / "_tmp"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.sqlite")
    import data_provider
    from services import dashboard, security
    monkeypatch.setattr(data_provider, "_instance", data_provider.GlobalPowerArchiveProvider())
    dashboard.reset_memo()
    security._failures.clear()
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def login(c, pw="password"):
    r = c.post("/api/auth/login", json={"username": "sarujan", "password": pw})
    return r


def auth(c):
    return {"Authorization": f"Bearer {login(c).json()['access_token']}"}


def test_default_login_and_protection(client):
    assert client.get("/api/dashboard/country_Sri_Lanka").status_code == 401
    r = login(client)
    assert r.status_code == 200 and r.json()["user"]["is_default_password"] is True
    assert login(client, "wrong").status_code == 401


def test_api_description_omits_personal_author_credit(client):
    description = client.get("/openapi.json").json()["info"]["description"]
    assert "Author:" not in description
    assert "saru.contacts@gmail.com" not in description


def test_dashboard_shape(client):
    h = auth(client)
    for country in ("country_Australia", "country_India", "country_United_Kingdom", "country_United_States_of_America"):
        r = client.get(f"/api/dashboard/{country}", headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source_mode"] == "ARCHIVE"
        assert d["fire"]["available"] is False and d["fire"]["detections"] is None
        assert d["vegetation"]["label"] == "Root-zone soil wetness"
        assert any("historical country" in m for m in d["model_methods"])
    for indicator in ("temperature", "vegetation", "precipitation", "fire"):
        assert client.get(f"/api/{indicator}/country_Australia", headers=h).status_code == 200


def test_region_and_unknown(client):
    h = auth(client)
    assert len(client.get("/api/locations", headers=h).json()) > 10
    assert client.get("/api/dashboard/country_Sri_Lanka", headers=h).status_code == 404
    assert client.get("/api/dashboard/Atlantis", headers=h).status_code == 404


def test_map_area_boundaries(client, tmp_path, monkeypatch):
    from routers import data as data_router

    path = tmp_path / "admin1.geojson.gz"
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"admin": "Testland", "name_en": "North"},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
            {"type": "Feature", "properties": {"admin": "Elsewhere", "name_en": "South"},
             "geometry": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]]}}
        ]
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(geojson, stream)
    monkeypatch.setattr(data_router, "ADMIN1_BOUNDARIES", path)
    data_router._admin1_features.cache_clear()
    try:
        response = client.get("/api/map/areas/Testland", headers=auth(client))
        assert response.status_code == 200
        assert [feature["properties"]["name"] for feature in response.json()["features"]] == ["North"]
        assert client.get("/api/map/areas/Missing", headers=auth(client)).status_code == 404
    finally:
        data_router._admin1_features.cache_clear()


def test_map_country_boundaries(client):
    response = client.get("/api/map/countries", headers=auth(client))
    assert response.status_code == 200
    names = {feature["properties"]["name"] for feature in response.json()["features"]}
    assert "Bangladesh" in names


def test_change_password_flow(client):
    h = auth(client)
    bad = client.post("/api/auth/change-password", headers=h, json={"current_password": "nope", "new_password": "Longer-pass1"})
    assert bad.status_code == 400
    short = client.post("/api/auth/change-password", headers=h, json={"current_password": "password", "new_password": "abc"})
    assert short.status_code == 422
    ok = client.post("/api/auth/change-password", headers=h, json={"current_password": "password", "new_password": "Longer-pass1"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401           # old token revoked
    new_h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new_h).json()["is_default_password"] is False
    assert login(client, "password").status_code == 401
    assert login(client, "Longer-pass1").status_code == 200


def test_lockout(client):
    for _ in range(5):
        assert login(client, "bad").status_code == 401
    assert login(client, "password").status_code == 429


def test_archive_only():
    from data_provider import PROVIDERS
    assert set(PROVIDERS) == {"archive"}


def test_bad_data_gives_clear_error_and_cache_fallback(client, monkeypatch):
    from services import dashboard
    from data_provider import DataError
    h = auth(client)
    assert client.get("/api/dashboard/country_Australia", headers=h).status_code == 200
    def fail(location):
        raise DataError("Archive unavailable")
    monkeypatch.setattr(dashboard, "_build", fail)
    r = client.get("/api/dashboard/country_Australia", headers=h)
    assert r.status_code == 200 and r.json()["served_from_cache"] is True
    assert client.get("/api/dashboard/country_India", headers=h).status_code == 503
