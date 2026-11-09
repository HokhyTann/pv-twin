import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.db import get_engine

router = APIRouter(prefix="/assets", tags=["assets"])


class AssetRef(BaseModel):
    asset_id: int
    asset_type: str
    code: str


class AssetEvent(BaseModel):
    day: dt.date
    scope: str
    category: str
    note: str


class AssetDetail(BaseModel):
    asset_id: int
    site_code: str
    site_name: str
    asset_type: str
    code: str
    attrs: dict[str, Any]
    lon: float | None
    lat: float | None
    ancestors: list[AssetRef]  # nearest parent first, up to the substation
    children: dict[str, int]  # direct children by type
    downstream_dc_kwp: float | None  # sum of table kWp below this asset
    events: list[AssetEvent]  # this asset's log entries + site-wide ones (ALL, COMMS)


@router.get("/{asset_id}", response_model=AssetDetail)
def asset_detail(asset_id: int) -> AssetDetail:
    with get_engine().connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                select a.asset_id, s.site_code, s.name site_name, a.asset_type, a.code,
                       a.attrs, a.site_id,
                       st_x(st_pointonsurface(a.geom)) lon, st_y(st_pointonsurface(a.geom)) lat
                from core.asset a join core.site s using (site_id)
                where a.asset_id = :id
                """
                ),
                {"id": asset_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(404, f"unknown asset {asset_id}")

        ancestors = conn.execute(
            text(
                """
                with recursive up as (
                  select parent_id, 1 depth from core.asset where asset_id = :id
                  union all
                  select a.parent_id, u.depth + 1 from up u
                  join core.asset a on a.asset_id = u.parent_id
                  where u.depth < 20
                )
                select a.asset_id, a.asset_type, a.code
                from up join core.asset a on a.asset_id = up.parent_id
                order by up.depth
                """
            ),
            {"id": asset_id},
        ).mappings()
        children = dict(
            conn.execute(
                text(
                    "select asset_type, count(*) from core.asset where parent_id = :id group by 1"
                ),
                {"id": asset_id},
            ).all()
        )
        dc = conn.execute(
            text(
                """
                with recursive down as (
                  select asset_id, asset_type, attrs from core.asset where asset_id = :id
                  union all
                  select a.asset_id, a.asset_type, a.attrs from down d
                  join core.asset a on a.parent_id = d.asset_id
                  where d.asset_type <> 'table'
                )
                select sum((attrs ->> 'kwp')::numeric)::float from down
                where asset_type = 'table'
                """
            ),
            {"id": asset_id},
        ).scalar()
        events = conn.execute(
            text(
                """
                select day, scope, category, note from clean.event
                where site_id = :site and (asset_id = :id or asset_id is null)
                order by day
                """
            ),
            {"site": row["site_id"], "id": asset_id},
        ).mappings()

        return AssetDetail(
            **{k: v for k, v in row.items() if k != "site_id"},
            ancestors=[AssetRef(**a) for a in ancestors],
            children=children,
            downstream_dc_kwp=dc,
            events=[AssetEvent(**e) for e in events],
        )
