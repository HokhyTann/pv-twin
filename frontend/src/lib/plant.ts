import type {
  AssetFeature,
  AssetType,
  CableFeature,
  Position,
  SiteFeature,
  SiteLayout,
} from '../api/types'

export type Bounds = [[number, number], [number, number]] // [[minLon, minLat], [maxLon, maxLat]]

/** Lookup tables over one site's layout, built once per layout version. */
export type PlantIndex = {
  byId: Map<number, AssetFeature>
  children: Map<number, number[]>
  /** each asset has at most one outgoing cable (table->combiner->inverter->transformer->...) */
  cableFrom: Map<number, CableFeature>
  byType: Record<AssetType, AssetFeature[]>
  cables: CableFeature[]
  features: Record<SiteFeature['properties']['kind'], SiteFeature[]>
}

const ASSET_TYPES: AssetType[] = [
  'substation',
  'meter',
  'transformer',
  'inverter',
  'combiner',
  'table',
  'string',
]

export function buildIndex(layout: SiteLayout): PlantIndex {
  const byId = new Map<number, AssetFeature>()
  const children = new Map<number, number[]>()
  const byType = Object.fromEntries(ASSET_TYPES.map((t) => [t, []])) as unknown as Record<
    AssetType,
    AssetFeature[]
  >
  for (const f of layout.assets.features) {
    const p = f.properties
    byId.set(p.id, f)
    byType[p.type].push(f)
    if (p.parent !== null) {
      const list = children.get(p.parent)
      if (list) list.push(p.id)
      else children.set(p.parent, [p.id])
    }
  }
  const cableFrom = new Map<number, CableFeature>()
  for (const c of layout.cables.features) cableFrom.set(c.properties.from, c)

  const features = { fence: [], road: [], block: [] } as PlantIndex['features']
  for (const f of layout.features.features) features[f.properties.kind].push(f)

  return { byId, children, cableFrom, byType, cables: layout.cables.features, features }
}

/** Parent chain, nearest first (not including the asset itself). */
export function ancestors(ix: PlantIndex, id: number): number[] {
  const out: number[] = []
  let cur = ix.byId.get(id)?.properties.parent ?? null
  while (cur !== null && out.length < 20) {
    out.push(cur)
    cur = ix.byId.get(cur)?.properties.parent ?? null
  }
  return out
}

export type Trace = { assets: Set<number>; cables: Set<number> }

/**
 * Electrical path from an asset up to the substation: its parent chain plus the cables
 * that physically carry its power. MV feeders are daisy-chained, so following cables can
 * pass through other transformers on the same feeder; those are included too.
 */
export function traceUpstream(ix: PlantIndex, id: number): Trace {
  const assets = new Set<number>([id, ...ancestors(ix, id)])
  const cables = new Set<number>()
  // Start at the first asset on the chain that has an outgoing cable (strings have none).
  let cur: number | undefined = [id, ...ancestors(ix, id)].find((a) => ix.cableFrom.has(a))
  while (cur !== undefined && cables.size < 50) {
    const c = ix.cableFrom.get(cur)
    if (!c || cables.has(c.properties.id)) break
    cables.add(c.properties.id)
    assets.add(c.properties.to)
    cur = c.properties.to
  }
  return { assets, cables }
}

/** The asset and everything below it in the tree. */
export function descendants(ix: PlantIndex, id: number): Set<number> {
  const out = new Set<number>([id])
  const stack = [id]
  while (stack.length) {
    for (const c of ix.children.get(stack.pop()!) ?? []) {
      out.add(c)
      stack.push(c)
    }
  }
  return out
}

function positions(f: AssetFeature): Position[] {
  return f.geometry.type === 'Point' ? [f.geometry.coordinates] : f.geometry.coordinates[0]
}

/** Bounding box of an asset and all its descendants (so zooming to an inverter shows its block). */
export function assetBounds(ix: PlantIndex, id: number): Bounds | null {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const d of descendants(ix, id)) {
    const f = ix.byId.get(d)
    if (!f) continue
    for (const [x, y] of positions(f)) {
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  return Number.isFinite(minX)
    ? [
        [minX, minY],
        [maxX, maxY],
      ]
    : null
}
