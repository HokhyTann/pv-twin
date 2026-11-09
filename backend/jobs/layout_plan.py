"""Synthetic plant layout, in local metres. Pure functions, no database.

Coordinates: x = east, y = north, metres, origin = site centre. The writer
(jobs.layout_gen) shifts them onto the site's UTM 48N position and stores WGS84.

Electrical tree produced (parent <- child):

    substation <- meter <- transformer <- inverter <- combiner <- table <- string

Physical arrangement:
- A *table* is one mounting structure: 2 x 28 modules in portrait, long axis east-west,
  facing south. Each of its two module rows is one *string* (28 x 600 Wp = 16.8 kWp).
- An inverter's tables form a *block*: `cols_per_block` columns, as many rows as needed.
- Two blocks share a *station*: a north-south corridor between them holds both inverters
  and one MV transformer. Combiner boxes stand on the block edge facing the corridor.
- Stations sit on a grid separated by roads. Each column of stations is one MV feeder,
  daisy-chained north to south and on to the substation south-west of the array.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

Point = tuple[float, float]


@dataclass(frozen=True)
class LayoutParams:
    module_wp: float = 600.0
    modules_per_string: int = 28
    strings_per_table: int = 2
    table_w: float = 33.0  # east-west length of a table, m
    table_d: float = 4.4  # north-south ground depth of a table (tilted), m
    table_gap: float = 1.0  # east-west gap between tables in a row, m
    row_pitch: float = 8.0  # north-south distance between table rows, m
    tilt_deg: float = 12.0
    cols_per_block: int = 4
    strings_per_combiner: int = 16
    corridor: float = 14.0  # width of the inverter corridor inside a station, m
    road: float = 8.0  # width of roads between stations, m
    fence_margin: float = 15.0
    default_inverter_dc_kwp: float = 3000.0
    dc_ac_ratio: float = 1.2

    @property
    def string_kwp(self) -> float:
        return self.module_wp * self.modules_per_string / 1000

    @property
    def table_kwp(self) -> float:
        return self.string_kwp * self.strings_per_table

    @property
    def tables_per_combiner(self) -> int:
        return max(1, self.strings_per_combiner // self.strings_per_table)


@dataclass(frozen=True)
class InverterSpec:
    code: str
    dc_kwp: float


@dataclass
class Asset:
    code: str
    asset_type: str
    parent_code: str | None
    geom: str  # WKT in local metres
    attrs: dict = field(default_factory=dict)


@dataclass
class Cable:
    from_code: str
    to_code: str
    kind: str
    path: list[Point]


@dataclass
class Feature:
    kind: str
    geom: str
    asset_code: str | None = None


@dataclass
class SiteLayout:
    assets: list[Asset]
    cables: list[Cable]
    features: list[Feature]
    bbox: tuple[float, float, float, float]  # minx, miny, maxx, maxy (array + substation)

    def stats(self) -> dict[str, float | int]:
        counts: dict[str, float | int] = {}
        for a in self.assets:
            counts[a.asset_type] = counts.get(a.asset_type, 0) + 1
        for c in self.cables:
            key = f"cable_{c.kind}_m"
            counts[key] = round(counts.get(key, 0) + path_length(c.path), 1)
        minx, miny, maxx, maxy = self.bbox
        counts["width_m"] = round(maxx - minx, 1)
        counts["height_m"] = round(maxy - miny, 1)
        return counts


# ---- geometry helpers ----------------------------------------------------------------------


def _f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v != 0 else "0"


def wkt_point(p: Point) -> str:
    return f"POINT({_f(p[0])} {_f(p[1])})"


def wkt_rect(x0: float, y0: float, x1: float, y1: float) -> str:
    """Axis-aligned rectangle; (x0, y0) and (x1, y1) are opposite corners."""
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    ring = [(xa, ya), (xb, ya), (xb, yb), (xa, yb), (xa, ya)]
    return "POLYGON((" + ", ".join(f"{_f(x)} {_f(y)}" for x, y in ring) + "))"


def wkt_line(path: list[Point]) -> str:
    return "LINESTRING(" + ", ".join(f"{_f(x)} {_f(y)}" for x, y in path) + ")"


def manhattan(*pts: Point) -> list[Point]:
    """Drop repeated points so every segment has length > 0."""
    out: list[Point] = []
    for p in pts:
        p = (round(p[0], 2), round(p[1], 2))
        if not out or out[-1] != p:
            out.append(p)
    if len(out) == 1:  # degenerate: give it a tiny stub so it is a valid line
        out.append((out[0][0], out[0][1] - 0.5))
    return out


def path_length(path: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(path, path[1:], strict=False))


def _num(code: str) -> str:
    """'INV-07' -> '07' (fallback: whole code)."""
    return code.rsplit("-", 1)[-1]


# ---- planning -------------------------------------------------------------------------------


@dataclass
class _Block:
    inv: InverterSpec
    n_tables: int
    rows: int
    w: float
    h: float


def _block(inv: InverterSpec, p: LayoutParams) -> _Block:
    n = max(1, round(inv.dc_kwp / p.table_kwp))
    rows = math.ceil(n / p.cols_per_block)
    cols = min(p.cols_per_block, n)
    w = cols * p.table_w + (cols - 1) * p.table_gap
    h = (rows - 1) * p.row_pitch + p.table_d
    return _Block(inv, n, rows, w, h)


def plan_site(inverters: list[InverterSpec], p: LayoutParams | None = None) -> SiteLayout:
    """Lay out a whole site for the given inverters (in the given order)."""
    p = p or LayoutParams()
    if not inverters:
        raise ValueError("a site needs at least one inverter")

    blocks = [_block(inv, p) for inv in inverters]
    stations = [blocks[i : i + 2] for i in range(0, len(blocks), 2)]

    block_w = max(b.w for b in blocks)
    station_w = 2 * block_w + p.corridor
    station_h = max(b.h for b in blocks)
    n_st = len(stations)
    n_cols = max(1, min(n_st, round(math.sqrt(n_st * station_h / station_w))))
    n_rows = math.ceil(n_st / n_cols)

    total_w = n_cols * station_w + (n_cols - 1) * p.road
    total_h = n_rows * station_h + (n_rows - 1) * p.road
    # Array spans x in [-total_w/2, total_w/2], y in [-total_h/2, total_h/2].
    ox, oy = -total_w / 2, total_h / 2

    assets: list[Asset] = []
    cables: list[Cable] = []
    features: list[Feature] = []

    # Substation + meter south-west of the array, outside the south perimeter road.
    sub_c = (ox - 20.0, oy - total_h - p.road - 25.0)
    assets.append(
        Asset(
            "SUB-01",
            "substation",
            None,
            wkt_rect(sub_c[0] - 20, sub_c[1] - 12, sub_c[0] + 20, sub_c[1] + 12),
            {"voltage_kv": "22/115"},
        )
    )
    meter_pt = (sub_c[0] + 12.0, sub_c[1])
    assets.append(Asset("MTR-01", "meter", "SUB-01", wkt_point(meter_pt), {"role": "revenue"}))
    south_road_y = oy - total_h - p.road / 2

    feeders: dict[int, list[tuple[str, Point]]] = {}  # station column -> transformers N->S

    for s_idx, st in enumerate(stations):
        col, row = s_idx % n_cols, s_idx // n_cols
        sx = ox + col * (station_w + p.road)
        sy = oy - row * (station_h + p.road)
        cx = sx + block_w + p.corridor / 2  # corridor centre line
        skid_y = sy - station_h / 2

        tx_code = f"TX-{s_idx + 1:02d}"
        tx_pt = (cx, skid_y - 6.0)
        assets.append(
            Asset(
                tx_code,
                "transformer",
                "MTR-01",
                wkt_point(tx_pt),
                {
                    "rating_kva": round(sum(b.inv.dc_kwp for b in st) / p.dc_ac_ratio / 100) * 100,
                    "station": s_idx + 1,
                },
            )
        )
        feeders.setdefault(col, []).append((tx_code, tx_pt))

        for side, b in zip(("W", "E"), st, strict=False):
            # West block's east edge faces the corridor, and vice versa.
            bx0 = sx if side == "W" else cx + p.corridor / 2
            edge_x = bx0 + block_w if side == "W" else bx0
            step = 1 if side == "W" else -1  # +x points toward the corridor (W)
            inv_pt = (cx - 3.0 if side == "W" else cx + 3.0, skid_y)
            inv = b.inv
            n2 = _num(inv.code)
            assets.append(
                Asset(
                    inv.code,
                    "inverter",
                    tx_code,
                    wkt_point(inv_pt),
                    {
                        "dc_kwp": round(inv.dc_kwp, 1),
                        "n_tables": b.n_tables,
                        "station": s_idx + 1,
                        "side": side,
                    },
                )
            )
            cables.append(
                Cable(inv.code, tx_code, "ac_lv", manhattan(inv_pt, (inv_pt[0], tx_pt[1]), tx_pt))
            )
            features.append(
                Feature("block", wkt_rect(bx0, sy + 2, bx0 + block_w, sy - b.h - 2), inv.code)
            )

            # Combiners: one per group of consecutive table rows.
            rows_per_cb = max(1, p.tables_per_combiner // p.cols_per_block)
            n_cb = math.ceil(b.rows / rows_per_cb)
            cb_pts: list[Point] = []
            cb_assets: list[Asset] = []
            for k in range(n_cb):
                r0, r1 = k * rows_per_cb, min(b.rows, (k + 1) * rows_per_cb) - 1
                y_mid = sy - (r0 + r1) / 2 * p.row_pitch - p.table_d / 2
                cb_pt = (edge_x + step * 2.0, y_mid)
                cb_pts.append(cb_pt)
                cb_code = f"CB-{n2}-{k + 1:02d}"
                cb_assets.append(
                    Asset(cb_code, "combiner", inv.code, wkt_point(cb_pt), {"n_strings": 0})
                )
                cables.append(
                    Cable(
                        cb_code,
                        inv.code,
                        "dc_main",
                        manhattan(cb_pt, (cb_pt[0], inv_pt[1]), inv_pt),
                    )
                )

            # Tables, filled row by row; within a row, start at the corridor side.
            assets += cb_assets
            for t in range(b.n_tables):
                r, c = divmod(t, p.cols_per_block)
                # c = 0 is the column nearest the corridor
                if side == "W":
                    x1 = bx0 + block_w - c * (p.table_w + p.table_gap)
                    x0 = x1 - p.table_w
                    near_x = x1
                else:
                    x0 = bx0 + c * (p.table_w + p.table_gap)
                    x1 = x0 + p.table_w
                    near_x = x0
                y_top = sy - r * p.row_pitch
                y_bot = y_top - p.table_d
                y_mid = (y_top + y_bot) / 2
                k = r // rows_per_cb
                cb_code = f"CB-{n2}-{k + 1:02d}"
                tbl_code = f"TBL-{n2}-{t + 1:03d}"
                assets.append(
                    Asset(
                        tbl_code,
                        "table",
                        cb_code,
                        wkt_rect(x0, y_top, x1, y_bot),
                        {
                            "kwp": round(p.table_kwp, 2),
                            "modules": p.modules_per_string * p.strings_per_table,
                            "tilt_deg": p.tilt_deg,
                            "azimuth_deg": 180,
                            "row": r + 1,
                            "col": c + 1,
                        },
                    )
                )
                cables.append(
                    Cable(
                        tbl_code,
                        cb_code,
                        "dc_string",
                        manhattan((near_x, y_mid), (cb_pts[k][0], y_mid), cb_pts[k]),
                    )
                )
                # Strings: the table's module rows, north to south.
                h = p.table_d / p.strings_per_table
                for s in range(p.strings_per_table):
                    ya = y_top - s * h
                    assets.append(
                        Asset(
                            f"STR-{n2}-{t + 1:03d}-{chr(97 + s)}",
                            "string",
                            tbl_code,
                            wkt_rect(x0, ya, x1, ya - h),
                            {"kwp": round(p.string_kwp, 2), "modules": p.modules_per_string},
                        )
                    )
                cb_assets[k].attrs["n_strings"] += p.strings_per_table

    # MV feeders: each station column is chained north -> south, then to the substation.
    for _col, txs in sorted(feeders.items()):
        for (a_code, a_pt), (b_code, b_pt) in zip(txs, txs[1:], strict=False):
            cables.append(Cable(a_code, b_code, "mv", manhattan(a_pt, (a_pt[0], b_pt[1]), b_pt)))
        last_code, last_pt = txs[-1]
        cables.append(
            Cable(
                last_code,
                "SUB-01",
                "mv",
                manhattan(
                    last_pt,
                    (last_pt[0], south_road_y),
                    (sub_c[0], south_road_y),
                    (sub_c[0], sub_c[1] + 12),
                ),
            )
        )

    # Roads: perimeter ring plus the gaps between station rows and columns.
    r = p.road
    x_min, x_max, y_max, y_min = ox, ox + total_w, oy, oy - total_h
    road_rects = [
        (x_min - r, y_max, x_max + r, y_max + r),  # north
        (x_min - r, y_min - r, x_max + r, y_min),  # south
        (x_min - r, y_min, x_min, y_max),  # west
        (x_max, y_min, x_max + r, y_max),  # east
    ]
    for i in range(1, n_cols):
        gx = ox + i * station_w + (i - 1) * r
        road_rects.append((gx, y_min, gx + r, y_max))
    for j in range(1, n_rows):
        gy = oy - j * station_h - (j - 1) * r
        road_rects.append((x_min, gy - r, x_max, gy))
    features += [Feature("road", wkt_rect(*rect)) for rect in road_rects]

    bminx = min(x_min - r, sub_c[0] - 20)
    bminy = min(y_min - r, sub_c[1] - 12)
    bmaxx, bmaxy = x_max + r, y_max + r
    m = p.fence_margin
    features.append(Feature("fence", wkt_rect(bminx - m, bminy - m, bmaxx + m, bmaxy + m)))

    return SiteLayout(assets, cables, features, (bminx, bminy, bmaxx, bmaxy))


def layout_version(inverters: list[InverterSpec], p: LayoutParams) -> str:
    """Stable hash of everything the layout depends on (use as an HTTP ETag)."""
    payload = json.dumps(
        {"params": asdict(p), "inverters": [asdict(i) for i in inverters]}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
