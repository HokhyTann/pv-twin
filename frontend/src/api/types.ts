// Hand-written mirrors of the FastAPI response models (backend/app/routers/*.py).
// openapi-typescript can't run on TypeScript 7 yet; keep these in sync by hand.

export type SiteSummary = {
  site_id: number
  site_code: string
  name: string
  capacity_dc_kwp: number | null
  lon: number
  lat: number
  source_dataset: string
  layout_version: string | null
  n_inverters: number
}

export type AssetType =
  | 'substation'
  | 'meter'
  | 'transformer'
  | 'inverter'
  | 'combiner'
  | 'table'
  | 'string'

export type TreeNode = {
  asset_id: number
  parent_id: number | null
  asset_type: AssetType
  code: string
  n_children: number
}

export type AssetRef = { asset_id: number; asset_type: AssetType; code: string }

export type AssetEvent = { day: string; scope: string; category: string; note: string }

export type AssetDetail = {
  asset_id: number
  site_code: string
  site_name: string
  asset_type: AssetType
  code: string
  attrs: Record<string, unknown>
  lon: number | null
  lat: number | null
  ancestors: AssetRef[]
  children: Partial<Record<AssetType, number>>
  downstream_dc_kwp: number | null
  events: AssetEvent[]
}

// ---- /sites/{code}/layout (GeoJSON built in PostGIS, WGS84) ----------------------------

export type Position = [number, number]
type Polygon = { type: 'Polygon'; coordinates: Position[][] }
type Point = { type: 'Point'; coordinates: Position }
type LineString = { type: 'LineString'; coordinates: Position[] }

export type AssetFeature = {
  type: 'Feature'
  geometry: Polygon | Point
  properties: { id: number; code: string; type: AssetType; parent: number | null }
}

export type CableKind = 'dc_string' | 'dc_main' | 'ac_lv' | 'mv' | 'comms'

export type CableFeature = {
  type: 'Feature'
  geometry: LineString
  properties: { id: number; kind: CableKind; from: number; to: number; length_m: number }
}

export type SiteFeature = {
  type: 'Feature'
  geometry: Polygon
  properties: { id: number; kind: 'fence' | 'road' | 'block'; asset: number | null }
}

type FC<F> = { type: 'FeatureCollection'; features: F[] }

export type SiteLayout = {
  site_code: string
  version: string
  bbox: [number, number, number, number]
  assets: FC<AssetFeature>
  cables: FC<CableFeature>
  features: FC<SiteFeature>
}
