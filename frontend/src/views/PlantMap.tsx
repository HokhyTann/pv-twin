import { WebMercatorViewport, type MapViewState, type PickingInfo } from '@deck.gl/core'
import { DeckGL } from '@deck.gl/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { AssetFeature, CableFeature } from '../api/types'
import { plantLayers, type Highlight } from '../layers/plantLayers'
import type { Bounds, PlantIndex } from '../lib/plant'
import { useTwin } from '../state/store'

export type FocusRequest = { bounds: Bounds; maxZoom: number; n: number }

type Props = {
  ix: PlantIndex
  siteBounds: Bounds
  layoutVersion: string
  hl: Highlight
  focus: FocusRequest | null
  onSelect: (id: number | null) => void
  onZoom: (z: number) => void
}

const CABLE_LABEL: Record<string, string> = {
  dc_string: 'DC string cable',
  dc_main: 'DC main cable',
  ac_lv: 'AC LV cable',
  mv: 'MV cable',
}

function fit(bounds: Bounds, el: HTMLElement | null, maxZoom: number): MapViewState {
  const width = el?.clientWidth || 800
  const height = el?.clientHeight || 600
  const pad = Math.min(48, width / 6, height / 6)
  const { longitude, latitude, zoom } = new WebMercatorViewport({ width, height }).fitBounds(
    bounds,
    { padding: pad, maxZoom },
  )
  return { longitude, latitude, zoom, pitch: 0, bearing: 0 }
}

function isCable(o: unknown): o is CableFeature {
  return typeof o === 'object' && o !== null && 'kind' in ((o as CableFeature).properties ?? {})
}

export default function PlantMap({
  ix,
  siteBounds,
  layoutVersion,
  hl,
  focus,
  onSelect,
  onZoom,
}: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<MapViewState | null>(null)
  const visible = useTwin((s) => s.visible)

  // Fit the whole site whenever a (new) layout arrives.
  useEffect(() => {
    setView(fit(siteBounds, box.current, 18))
    // Refit only for a new layout version (siteBounds is derived from it, and refitting
    // on every new array identity would undo the user's pan/zoom).
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutVersion])

  // Zoom to an asset when asked (n changes on every request, even for the same asset).
  useEffect(() => {
    if (focus) setView((v) => ({ ...(v ?? {}), ...fit(focus.bounds, box.current, focus.maxZoom) }))
  }, [focus])

  const zoom = view?.zoom ?? 15
  useEffect(() => onZoom(zoom), [zoom, onZoom])

  // Zoom is bucketed so layers rebuild only when crossing a visibility threshold.
  const zoomBucket = Math.floor(zoom * 2) / 2
  const layers = useMemo(
    () => plantLayers({ ix, on: visible, zoom: zoomBucket, hl }),
    [ix, visible, zoomBucket, hl],
  )

  const tooltip = ({ object }: PickingInfo) => {
    if (!object) return null
    if (isCable(object)) {
      const p = object.properties
      return { text: `${CABLE_LABEL[p.kind] ?? p.kind} · ${Math.round(p.length_m)} m` }
    }
    const p = (object as AssetFeature).properties
    return p?.code ? { text: `${p.code} · ${p.type}` } : null
  }

  return (
    <div ref={box} className="absolute inset-0 bg-[#e9e5da]">
      {view && (
        <DeckGL
          viewState={view}
          onViewStateChange={({ viewState }) => setView(viewState as MapViewState)}
          controller={{ dragRotate: false, touchRotate: false }}
          layers={layers}
          getTooltip={tooltip}
          onClick={(info) => {
            const o = info.object as AssetFeature | CableFeature | undefined
            if (!o || isCable(o)) onSelect(isCable(o) ? o.properties.from : null)
            else onSelect(o.properties.id)
          }}
        />
      )}
    </div>
  )
}
