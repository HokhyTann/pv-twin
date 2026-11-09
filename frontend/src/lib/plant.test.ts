import { describe, expect, it } from 'vitest'
import type { AssetFeature, AssetType, CableFeature, SiteLayout } from '../api/types'
import { ancestors, assetBounds, buildIndex, descendants, traceUpstream } from './plant'

// Tiny plant: SUB(1) <- MTR(2) <- TX-A(3), TX-B(4) ; TX-A <- INV(5) <- CB(6) <- TBL(7) <- STR(8, 9)
// MV feeder is daisy-chained: TX-B -> TX-A -> SUB.
const pt = (x: number, y: number) => ({ type: 'Point' as const, coordinates: [x, y] as [number, number] })
const sq = (x: number, y: number, s = 1) => ({
  type: 'Polygon' as const,
  coordinates: [
    [
      [x, y],
      [x + s, y],
      [x + s, y + s],
      [x, y + s],
      [x, y],
    ] as [number, number][],
  ],
})
const asset = (
  id: number,
  type: AssetType,
  parent: number | null,
  geometry: AssetFeature['geometry'],
): AssetFeature => ({ type: 'Feature', geometry, properties: { id, code: `${type}-${id}`, type, parent } })
const cable = (id: number, from: number, to: number, kind: CableFeature['properties']['kind']): CableFeature => ({
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] },
  properties: { id, kind, from, to, length_m: 1 },
})

const layout: SiteLayout = {
  site_code: 'T',
  version: 'v',
  bbox: [0, 0, 10, 10],
  assets: {
    type: 'FeatureCollection',
    features: [
      asset(1, 'substation', null, sq(0, 0, 2)),
      asset(2, 'meter', 1, pt(1, 1)),
      asset(3, 'transformer', 2, pt(5, 5)),
      asset(4, 'transformer', 2, pt(5, 8)),
      asset(5, 'inverter', 3, pt(5, 6)),
      asset(6, 'combiner', 5, pt(6, 6)),
      asset(7, 'table', 6, sq(7, 7)),
      asset(8, 'string', 7, sq(7, 7.5, 0.5)),
      asset(9, 'string', 7, sq(7, 7, 0.5)),
    ],
  },
  cables: {
    type: 'FeatureCollection',
    features: [
      cable(100, 7, 6, 'dc_string'),
      cable(101, 6, 5, 'dc_main'),
      cable(102, 5, 3, 'ac_lv'),
      cable(103, 4, 3, 'mv'),
      cable(104, 3, 1, 'mv'),
    ],
  },
  features: { type: 'FeatureCollection', features: [] },
}

const ix = buildIndex(layout)

describe('plant index', () => {
  it('groups assets by type', () => {
    expect(ix.byType.string.map((f) => f.properties.id)).toEqual([8, 9])
    expect(ix.byType.transformer).toHaveLength(2)
  })

  it('walks the parent chain nearest first', () => {
    expect(ancestors(ix, 8)).toEqual([7, 6, 5, 3, 2, 1])
    expect(ancestors(ix, 1)).toEqual([])
  })

  it('collects an asset and everything below it', () => {
    expect([...descendants(ix, 5)].sort()).toEqual([5, 6, 7, 8, 9])
    expect([...descendants(ix, 8)]).toEqual([8])
  })
})

describe('traceUpstream', () => {
  it('starts a string trace at its table cable and follows cables to the substation', () => {
    const t = traceUpstream(ix, 8)
    expect([...t.cables]).toEqual([100, 101, 102, 104])
    expect([...t.assets].sort((a, b) => a - b)).toEqual([1, 2, 3, 5, 6, 7, 8])
  })

  it('follows a daisy-chained MV feeder through the other transformer', () => {
    const t = traceUpstream(ix, 4)
    expect([...t.cables]).toEqual([103, 104])
    expect(t.assets.has(3)).toBe(true) // passes through TX-A on its way to the substation
  })

  it('has no cables for the substation itself', () => {
    expect(traceUpstream(ix, 1).cables.size).toBe(0)
  })
})

describe('assetBounds', () => {
  it('covers the asset and all its descendants', () => {
    expect(assetBounds(ix, 5)).toEqual([
      [5, 6],
      [8, 8],
    ])
  })

  it('is null for an unknown asset', () => {
    expect(assetBounds(ix, 999)).toBeNull()
  })
})
