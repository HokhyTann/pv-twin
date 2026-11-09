from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.db import get_engine

router = APIRouter(prefix="/sites", tags=["sites"])


class SiteSummary(BaseModel):
    site_id: int
    site_code: str
    name: str
    capacity_dc_kwp: float | None
    lon: float
    lat: float
    source_dataset: str
    layout_version: str | None
    n_inverters: int


class TreeNode(BaseModel):
    asset_id: int
    parent_id: int | None
    asset_type: str
    code: str
    n_children: int


@router.get("", response_model=list[SiteSummary])
def list_sites() -> list[SiteSummary]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                select s.site_id, s.site_code, s.name, s.capacity_dc_kwp::float,
                       st_x(s.location) lon, st_y(s.location) lat, s.source_dataset,
                       l.version layout_version,
                       (select count(*) from core.asset a
                        where a.site_id = s.site_id and a.asset_type = 'inverter') n_inverters
                from core.site s left join core.layout_run l using (site_id)
                order by s.site_code
                """
            )
        ).mappings()
        return [SiteSummary(**r) for r in rows]


# One SQL statement builds the whole response, so Python never re-serialises ~10k features.
LAYOUT_SQL = """
with s as (select site_id, site_code from core.site where site_code = :code)
select json_build_object(
  'site_code', s.site_code,
  'version',   l.version,
  'bbox',      (select json_build_array(st_xmin(e), st_ymin(e), st_xmax(e), st_ymax(e))
                from (select st_extent(geom) e from core.site_feature f
                      where f.site_id = s.site_id and f.kind = 'fence') x),
  'assets', (
    select json_build_object('type', 'FeatureCollection', 'features',
             coalesce(json_agg(json_build_object(
               'type', 'Feature',
               'geometry', st_asgeojson(a.geom, 6)::json,
               'properties', json_build_object(
                 'id', a.asset_id, 'code', a.code, 'type', a.asset_type,
                 'parent', a.parent_id)) order by a.asset_id), '[]'::json))
    from core.asset a where a.site_id = s.site_id and a.geom is not null),
  'cables', (
    select json_build_object('type', 'FeatureCollection', 'features',
             coalesce(json_agg(json_build_object(
               'type', 'Feature',
               'geometry', st_asgeojson(c.geom, 6)::json,
               'properties', json_build_object(
                 'id', c.cable_id, 'kind', c.kind, 'from', c.from_asset, 'to', c.to_asset,
                 'length_m', c.length_m)) order by c.cable_id), '[]'::json))
    from core.cable c where c.site_id = s.site_id),
  'features', (
    select json_build_object('type', 'FeatureCollection', 'features',
             coalesce(json_agg(json_build_object(
               'type', 'Feature',
               'geometry', st_asgeojson(f.geom, 6)::json,
               'properties', json_build_object(
                 'id', f.feature_id, 'kind', f.kind, 'asset', f.asset_id))
               order by f.feature_id), '[]'::json))
    from core.site_feature f where f.site_id = s.site_id)
)::text
from s join core.layout_run l using (site_id)
"""


@router.get(
    "/{site_code}/layout",
    responses={
        200: {
            "description": "Site layout: {site_code, version, bbox, assets, cables, features}"
            " where assets/cables/features are GeoJSON FeatureCollections (WGS84)."
        },
        304: {"description": "Not modified (If-None-Match matched the layout version)"},
        404: {"description": "Unknown site or no layout generated"},
    },
)
def site_layout(site_code: str, request: Request) -> Response:
    """Whole-site geometry. Cache with the ETag: it only changes when the layout is regenerated."""
    with get_engine().connect() as conn:
        version = conn.execute(
            text(
                "select l.version from core.layout_run l join core.site s using (site_id)"
                " where s.site_code = :code"
            ),
            {"code": site_code},
        ).scalar()
        if version is None:
            raise HTTPException(404, f"no layout for site {site_code!r}")
        etag = f'"{version}"'
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        body = conn.execute(text(LAYOUT_SQL), {"code": site_code}).scalar_one()
    return Response(body, media_type="application/json", headers=headers)


@router.get("/{site_code}/tree", response_model=list[TreeNode])
def site_tree(site_code: str) -> list[TreeNode]:
    """Asset tree down to combiner level (tables and strings are selected on the map)."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                select a.asset_id, a.parent_id, a.asset_type, a.code,
                       (select count(*) from core.asset c where c.parent_id = a.asset_id)
                         n_children
                from core.asset a join core.site s using (site_id)
                where s.site_code = :code
                  and a.asset_type in ('substation', 'meter', 'transformer', 'inverter',
                                       'combiner')
                order by a.code
                """
            ),
            {"code": site_code},
        ).mappings()
        nodes = [TreeNode(**r) for r in rows]
    if not nodes:
        raise HTTPException(404, f"unknown site {site_code!r}")
    return nodes
