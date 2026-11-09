"""API tests against pv_test (fixture data, layout generated)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_engine
from jobs import layout_gen


@pytest.fixture(scope="module")
def client(loaded_db: str) -> Iterator[TestClient]:
    layout_gen.run(dsn=loaded_db)
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = loaded_db.replace("postgresql://", "postgresql+psycopg://", 1)
    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    try:
        yield TestClient(app)
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()
        get_engine.cache_clear()


def test_sites_list(client: TestClient) -> None:
    sites = {s["site_code"]: s for s in client.get("/api/v1/sites").json()}
    assert len(sites) == 9
    assert sites["KH-D06"]["n_inverters"] == 3
    assert sites["KH-D06"]["layout_version"]


def test_layout_geojson_and_etag(client: TestClient) -> None:
    r = client.get("/api/v1/sites/KH-D06/layout")
    assert r.status_code == 200
    body = r.json()
    types = {f["properties"]["type"] for f in body["assets"]["features"]}
    assert {
        "substation",
        "meter",
        "transformer",
        "inverter",
        "combiner",
        "table",
        "string",
    } <= types
    kinds = {f["properties"]["kind"] for f in body["cables"]["features"]}
    assert kinds == {"dc_string", "dc_main", "ac_lv", "mv"}
    assert {f["properties"]["kind"] for f in body["features"]["features"]} == {
        "fence",
        "road",
        "block",
    }
    minx, miny, maxx, maxy = body["bbox"]
    assert 104 < minx < maxx < 105 and 11 < miny < maxy < 12  # KH-D06 near Kandal
    assert r.headers["etag"] == f'"{body["version"]}"'

    again = client.get("/api/v1/sites/KH-D06/layout", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_layout_is_gzipped(client: TestClient) -> None:
    r = client.get("/api/v1/sites/KH-A01/layout", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_unknown_site_404(client: TestClient) -> None:
    assert client.get("/api/v1/sites/NOPE/layout").status_code == 404
    assert client.get("/api/v1/sites/NOPE/tree").status_code == 404


def test_tree_stops_at_combiners(client: TestClient) -> None:
    nodes = client.get("/api/v1/sites/KH-D06/tree").json()
    assert {n["asset_type"] for n in nodes} == {
        "substation",
        "meter",
        "transformer",
        "inverter",
        "combiner",
    }
    roots = [n for n in nodes if n["parent_id"] is None]
    assert [r["asset_type"] for r in roots] == ["substation"]


def test_asset_detail_for_a_string(client: TestClient) -> None:
    layout = client.get("/api/v1/sites/KH-D06/layout").json()
    string = next(
        f["properties"] for f in layout["assets"]["features"] if f["properties"]["type"] == "string"
    )
    d = client.get(f"/api/v1/assets/{string['id']}").json()
    assert d["asset_type"] == "string"
    assert [a["asset_type"] for a in d["ancestors"]] == [
        "table",
        "combiner",
        "inverter",
        "transformer",
        "meter",
        "substation",
    ]
    assert d["downstream_dc_kwp"] is None


def test_asset_detail_for_an_inverter(client: TestClient) -> None:
    layout = client.get("/api/v1/sites/KH-D06/layout").json()
    inv = next(
        f["properties"]
        for f in layout["assets"]["features"]
        if f["properties"]["type"] == "inverter" and f["properties"]["code"] == "INV-03"
    )
    d = client.get(f"/api/v1/assets/{inv['id']}").json()
    assert d["attrs"]["rated_ac_kw"] == 2500 and d["attrs"]["model"] == "CI-2500"
    assert d["children"] == {"combiner": d["children"]["combiner"]} and d["children"]["combiner"]
    # 3000 kWp nameplate -> round(3000 / 33.6) = 89 tables x 33.6 kWp
    assert d["downstream_dc_kwp"] == pytest.approx(89 * 33.6)
    # its own firmware entry + site-wide entries with no asset (ALL); the meter test belongs
    # to the meter and the INV-02 trip to INV-02
    assert {(e["scope"], e["category"]) for e in d["events"]} == {
        ("INV-03", "firmware"),
        ("ALL", "cleaning"),
    }


def test_unknown_asset_404(client: TestClient) -> None:
    assert client.get("/api/v1/assets/999999999").status_code == 404
