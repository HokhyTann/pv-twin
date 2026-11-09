"""Render each site's generated layout to a static SVG page (a quick visual check).

Writes data/preview/index.html plus one <SITE>.html per site. Geometry is drawn in
UTM metres (true proportions) with PostGIS ST_AsSVG, so this needs no extra libraries.

Usage:  uv run python -m jobs.layout_preview [SITE_CODE ...]
"""

from __future__ import annotations

import argparse
import html
import logging
from pathlib import Path

import psycopg

from app.config import REPO_DIR, get_settings

log = logging.getLogger("layout_preview")
OUT = REPO_DIR / "data" / "preview"

# draw order: (layer name, SQL returning svg path data, style)
LAYERS = [
    (
        "fence",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.site_feature"
        " where site_id = %(s)s and kind = 'fence'",
        "fill:#f4f1ea;stroke:#7a6f5a;stroke-width:2;stroke-dasharray:8 6",
    ),
    (
        "road",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.site_feature"
        " where site_id = %(s)s and kind = 'road'",
        "fill:#d9d4c7;stroke:none",
    ),
    (
        "block",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.site_feature"
        " where site_id = %(s)s and kind = 'block'",
        "fill:none;stroke:#9aa7b8;stroke-width:1",
    ),
    (
        "table",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.asset"
        " where site_id = %(s)s and asset_type = 'table'",
        "fill:#2f5d8a;stroke:#1d3c5c;stroke-width:0.3",
    ),
    (
        "dc_string",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.cable"
        " where site_id = %(s)s and kind = 'dc_string'",
        "fill:none;stroke:#e0a83a;stroke-width:0.4;opacity:0.7",
    ),
    (
        "dc_main",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.cable"
        " where site_id = %(s)s and kind = 'dc_main'",
        "fill:none;stroke:#d9731f;stroke-width:1",
    ),
    (
        "mv",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.cable"
        " where site_id = %(s)s and kind in ('mv', 'ac_lv')",
        "fill:none;stroke:#c0392b;stroke-width:2.5",
    ),
    (
        "substation",
        "select st_assvg(st_transform(geom, 32648), 0, 1) from core.asset"
        " where site_id = %(s)s and asset_type = 'substation'",
        "fill:#5b4a8a;stroke:#2e2450;stroke-width:1",
    ),
]
POINTS = [  # (asset_type, radius m, fill)
    ("combiner", 1.6, "#d9731f"),
    ("inverter", 3.0, "#111"),
    ("transformer", 4.0, "#c0392b"),
    ("meter", 3.0, "#f5d142"),
]


def render_site(conn: psycopg.Connection, site_id: int, code: str, name: str) -> str:
    xmin, ymin, xmax, ymax = conn.execute(
        "select st_xmin(e), st_ymin(e), st_xmax(e), st_ymax(e) from (select"
        " st_extent(st_transform(geom, 32648))::box2d e from core.site_feature"
        " where site_id = %s and kind = 'fence') x",
        (site_id,),
    ).fetchone()
    pad = 10
    w, h = xmax - xmin + 2 * pad, ymax - ymin + 2 * pad
    vb = f"{xmin - pad:.1f} {-ymax - pad:.1f} {w:.1f} {h:.1f}"  # SVG y points down

    parts = []
    for name_, sql, style in LAYERS:
        d = " ".join(r[0] for r in conn.execute(sql, {"s": site_id}))
        if d:
            parts.append(f'<path class="{name_}" style="{style}" d="{d}"/>')
    for t, r, fill in POINTS:
        pts = conn.execute(
            "select st_x(g), st_y(g), code from (select st_transform(geom, 32648) g, code"
            " from core.asset where site_id = %s and asset_type = %s) x",
            (site_id, t),
        ).fetchall()
        circles = "".join(
            f'<circle cx="{x:.1f}" cy="{-y:.1f}" r="{r}"><title>{html.escape(c)}</title></circle>'
            for x, y, c in pts
        )
        parts.append(f'<g class="{t}" fill="{fill}">{circles}</g>')

    stats = conn.execute(
        "select stats from core.layout_run where site_id = %s", (site_id,)
    ).fetchone()[0]
    summary = (
        f"{stats['dc_kwp'] / 1000:.1f} MWp · {stats.get('inverter', 0)} inverters · "
        f"{stats.get('table', 0)} tables · {stats.get('combiner', 0)} combiners · "
        f"{stats['width_m']:.0f} × {stats['height_m']:.0f} m"
    )
    return f"""<!doctype html><meta charset="utf-8"><title>{code} layout</title>
<style>body{{font:14px system-ui;margin:16px;background:#fff;color:#222}}
svg{{width:100%;height:85vh;border:1px solid #ddd;background:#fbfaf7}}
.legend span{{margin-right:14px}} .legend i{{display:inline-block;width:12px;height:12px;
margin-right:4px;vertical-align:-2px}}</style>
<h2 style="margin:0">{html.escape(code)} · {html.escape(name)}</h2>
<p style="margin:4px 0 8px">{summary} · <em>synthetic layout</em> ·
<a href="index.html">all sites</a></p>
<div class="legend"><span><i style="background:#2f5d8a"></i>table</span>
<span><i style="background:#e0a83a"></i>DC string cable</span>
<span><i style="background:#d9731f"></i>combiner / DC main</span>
<span><i style="background:#111"></i>inverter</span>
<span><i style="background:#c0392b"></i>transformer / MV + LV AC</span>
<span><i style="background:#5b4a8a"></i>substation</span>
<span><i style="background:#f5d142"></i>meter</span>
<span><i style="background:#d9d4c7"></i>road</span></div>
<svg viewBox="{vb}" xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>"""


def run(site_codes: list[str] | None = None, dsn: str | None = None, out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = []
    with psycopg.connect(dsn or get_settings().dsn, autocommit=True) as conn:
        sites = conn.execute(
            "select s.site_id, s.site_code, s.name from core.site s"
            " join core.layout_run l using (site_id)"
            " where %s::text[] is null or s.site_code = any(%s) order by s.site_code",
            (site_codes, site_codes),
        ).fetchall()
        for site_id, code, name in sites:
            f = out / f"{code}.html"
            f.write_text(render_site(conn, site_id, code, name))
            files.append(f)
    links = "".join(f'<li><a href="{f.name}">{f.stem}</a></li>' for f in files)
    (out / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>Layouts</title>'
        f'<body style="font:14px system-ui;margin:16px"><h2>Generated layouts</h2>'
        f"<ul>{links}</ul>"
    )
    return files


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sites", nargs="*")
    for f in run(ap.parse_args().sites or None):
        log.info("wrote %s (%.0f kB)", f, f.stat().st_size / 1024)


if __name__ == "__main__":
    main()
