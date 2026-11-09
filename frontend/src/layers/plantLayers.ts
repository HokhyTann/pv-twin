import type { Color, Layer } from '@deck.gl/core'
import { GeoJsonLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import type { AssetFeature, CableFeature, Position } from '../api/types'
import type { PlantIndex, Trace } from '../lib/plant'
import { LAYERS, type LayerKey } from '../state/store'

export const COLORS = {
  fenceFill: [244, 241, 234],
  fenceLine: [122, 111, 90],
  road: [217, 212, 199],
  block: [154, 167, 184],
  table: [47, 93, 138],
  string: [86, 132, 178],
  dc_string: [224, 168, 58],
  dc_main: [217, 115, 31],
  ac: [192, 57, 43],
  combiner: [217, 115, 31],
  inverter: [24, 24, 27],
  transformer: [192, 57, 43],
  substation: [91, 74, 138],
  meter: [245, 209, 66],
  downstream: [242, 169, 59],
  trace: [214, 40, 120],
  selected: [255, 255, 255],
} satisfies Record<string, Color>

const DIM = 70 // alpha for unrelated items while something is selected

export type Highlight = {
  selected: number | null
  trace: Trace | null // upstream path (assets + cables)
  down: Set<number> | null // selected asset and everything below it
}

function rgba(c: Color, a = 255): Color {
  return [c[0], c[1], c[2], a]
}

export function visibleAt(k: LayerKey, zoom: number, on: Record<LayerKey, boolean>): boolean {
  const min = (LAYERS[k] as { minZoom?: number }).minZoom ?? 0
  return on[k] && zoom >= min
}

type Opts = {
  ix: PlantIndex
  on: Record<LayerKey, boolean>
  zoom: number
  hl: Highlight
}

export function plantLayers({ ix, on, zoom, hl }: Opts): Layer[] {
  const active = hl.selected !== null
  const key = `${hl.selected}|${hl.trace ? 't' : ''}`
  const inTrace = (id: number) => hl.trace?.assets.has(id) ?? false
  const inDown = (id: number) => hl.down?.has(id) ?? false

  /** Colour for an asset given its base colour and the current selection. */
  const assetColor =
    (base: Color) =>
    (f: { properties: { id: number; parent?: number | null } }): Color => {
      const id = f.properties.id
      if (!active) return rgba(base)
      // a selected table is drawn by its strings when they are shown, so they take its colour
      if (id === hl.selected || (f.properties.parent === hl.selected && ix.byId.get(id)?.properties.type === 'string'))
        return rgba(COLORS.trace)
      if (inDown(id)) return rgba(COLORS.downstream)
      if (inTrace(id)) return rgba(COLORS.trace)
      return rgba(base, DIM)
    }

  const cableColor =
    (base: Color) =>
    (c: CableFeature): Color => {
      if (!active) return rgba(base)
      if (hl.trace?.cables.has(c.properties.id)) return rgba(COLORS.trace)
      if (inDown(c.properties.from)) return rgba(COLORS.downstream)
      return rgba(base, DIM)
    }
  const cableWidth = (base: number) => (c: CableFeature) =>
    hl.trace?.cables.has(c.properties.id) ? base * 2.5 : base

  const point = (f: AssetFeature) => f.geometry.coordinates as Position
  const stringsShown = visibleAt('string', zoom, on)

  const layers: Layer[] = []

  // ---- site background ---------------------------------------------------------------
  if (on.fence)
    layers.push(
      new GeoJsonLayer({
        id: 'fence',
        data: ix.features.fence,
        filled: true,
        stroked: true,
        getFillColor: COLORS.fenceFill,
        getLineColor: COLORS.fenceLine,
        lineWidthUnits: 'pixels',
        getLineWidth: 1.5,
      }),
    )
  if (on.road)
    layers.push(
      new GeoJsonLayer({
        id: 'road',
        data: ix.features.road,
        filled: true,
        stroked: false,
        getFillColor: COLORS.road,
      }),
    )
  if (on.block)
    layers.push(
      new GeoJsonLayer({
        id: 'block',
        data: ix.features.block,
        filled: false,
        stroked: true,
        getLineColor: COLORS.block,
        lineWidthUnits: 'pixels',
        getLineWidth: 1,
      }),
    )

  // ---- PV array ----------------------------------------------------------------------
  if (on.table)
    layers.push(
      new GeoJsonLayer<AssetFeature['properties']>({
        id: 'table',
        data: ix.byType.table,
        // Strings exactly cover their table; while they are shown, clicks go to the string
        // (coplanar polygons would otherwise pick the table). The table stays one click away
        // in the breadcrumb.
        pickable: !stringsShown,
        autoHighlight: !stringsShown,
        highlightColor: [255, 255, 255, 90],
        filled: true,
        stroked: zoom >= 17,
        getFillColor: assetColor(COLORS.table),
        getLineColor: [20, 45, 70, 160],
        lineWidthUnits: 'pixels',
        getLineWidth: 0.5,
        updateTriggers: { getFillColor: key },
      }),
    )
  if (stringsShown)
    layers.push(
      new GeoJsonLayer<AssetFeature['properties']>({
        id: 'string',
        data: ix.byType.string,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 110],
        filled: true,
        stroked: true,
        getFillColor: assetColor(COLORS.string),
        getLineColor: [255, 255, 255, 140],
        lineWidthUnits: 'pixels',
        getLineWidth: 0.5,
        updateTriggers: { getFillColor: key },
      }),
    )

  // ---- cables ------------------------------------------------------------------------
  const cableLayer = (id: string, kinds: string[], base: Color, width: number) =>
    new PathLayer<CableFeature>({
      id,
      data: ix.cables.filter((c) => kinds.includes(c.properties.kind)),
      pickable: true,
      getPath: (c) => c.geometry.coordinates,
      getColor: cableColor(base),
      getWidth: cableWidth(width),
      widthUnits: 'meters',
      widthMinPixels: 1,
      capRounded: true,
      jointRounded: true,
      updateTriggers: { getColor: key, getWidth: key },
    })
  if (visibleAt('dc_string', zoom, on))
    layers.push(cableLayer('dc_string', ['dc_string'], COLORS.dc_string, 0.4))
  if (on.dc_main) layers.push(cableLayer('dc_main', ['dc_main'], COLORS.dc_main, 0.9))
  if (on.ac) layers.push(cableLayer('ac', ['ac_lv', 'mv'], COLORS.ac, 1.8))

  // The traced path is always drawn on top, whatever the zoom or layer toggles.
  if (hl.trace && hl.trace.cables.size)
    layers.push(
      new PathLayer<CableFeature>({
        id: 'trace',
        data: ix.cables.filter((c) => hl.trace!.cables.has(c.properties.id)),
        getPath: (c) => c.geometry.coordinates,
        getColor: rgba(COLORS.trace),
        getWidth: (c) => (c.properties.kind === 'dc_string' ? 1 : 2.5),
        widthUnits: 'meters',
        widthMinPixels: 2.5,
        capRounded: true,
        jointRounded: true,
      }),
    )

  // ---- equipment ---------------------------------------------------------------------
  if (on.substation)
    layers.push(
      new GeoJsonLayer<AssetFeature['properties']>({
        id: 'substation',
        data: ix.byType.substation,
        pickable: true,
        autoHighlight: true,
        filled: true,
        stroked: true,
        getFillColor: assetColor(COLORS.substation),
        getLineColor: [46, 36, 80],
        lineWidthUnits: 'pixels',
        getLineWidth: 1,
        updateTriggers: { getFillColor: key },
      }),
    )
  const points = (
    id: string,
    data: AssetFeature[],
    base: Color,
    radius: number,
    minPx: number,
  ) =>
    new ScatterplotLayer<AssetFeature>({
      id,
      data,
      pickable: true,
      autoHighlight: true,
      getPosition: point,
      getRadius: (f) => (f.properties.id === hl.selected ? radius * 1.6 : radius),
      radiusUnits: 'meters',
      radiusMinPixels: minPx,
      stroked: true,
      getFillColor: assetColor(base),
      getLineColor: (f) =>
        f.properties.id === hl.selected ? rgba(COLORS.selected) : [255, 255, 255, 180],
      lineWidthUnits: 'pixels',
      getLineWidth: (f) => (f.properties.id === hl.selected ? 2.5 : 1),
      updateTriggers: { getFillColor: key, getRadius: key, getLineColor: key, getLineWidth: key },
    })
  if (visibleAt('combiner', zoom, on))
    layers.push(points('combiner', ix.byType.combiner, COLORS.combiner, 1.2, 2.5))
  if (on.inverter) layers.push(points('inverter', ix.byType.inverter, COLORS.inverter, 2.2, 3.5))
  if (on.transformer)
    layers.push(points('transformer', ix.byType.transformer, COLORS.transformer, 3, 4))
  if (on.substation) layers.push(points('meter', ix.byType.meter, COLORS.meter, 2.5, 4))

  if (visibleAt('labels', zoom, on)) {
    // Two inverters share a skid 6 m apart: put each label on its own side of the corridor
    // (west of its transformer -> label to the left), transformer labels below.
    const westOfParent = (f: AssetFeature) => {
      const parent = f.properties.parent === null ? undefined : ix.byId.get(f.properties.parent)
      return parent?.geometry.type === 'Point' && point(f)[0] < parent.geometry.coordinates[0]
    }
    const labelled = [...ix.byType.inverter, ...ix.byType.transformer].filter(
      (f) => f.geometry.type === 'Point',
    )
    layers.push(
      new TextLayer<AssetFeature>({
        id: 'labels',
        data: labelled,
        getPosition: point,
        getText: (f) => f.properties.code,
        getSize: 11,
        getColor: [30, 30, 30],
        getTextAnchor: (f) =>
          f.properties.type === 'transformer' ? 'middle' : westOfParent(f) ? 'end' : 'start',
        getPixelOffset: (f) =>
          f.properties.type === 'transformer' ? [0, 16] : [westOfParent(f) ? -10 : 10, 0],
        background: true,
        getBackgroundColor: [255, 255, 255, 220],
        backgroundPadding: [3, 1],
        fontFamily: 'system-ui, sans-serif',
      }),
    )
  }
  return layers
}
