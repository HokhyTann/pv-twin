import { useCallback, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useLayout, useSites, useTree } from '../api/hooks'
import { COLORS, type Highlight } from '../layers/plantLayers'
import { ancestors, assetBounds, buildIndex, descendants, traceUpstream, type Bounds } from '../lib/plant'
import { useTwin } from '../state/store'
import AssetDrawer from './AssetDrawer'
import AssetTree from './AssetTree'
import LayerPanel from './LayerPanel'
import PlantMap, { type FocusRequest } from './PlantMap'

const swatch = (c: readonly number[]) => ({ background: `rgb(${c[0]},${c[1]},${c[2]})` })

export default function SiteTwin() {
  const { siteCode = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const layoutQ = useLayout(siteCode)
  const site = useSites().data?.find((s) => s.site_code === siteCode)
  const treeQ = useTree(siteCode)
  const showTrace = useTwin((s) => s.showTrace)
  const [zoom, setZoom] = useState(15)
  const [focus, setFocus] = useState<FocusRequest | null>(null)

  const ix = useMemo(() => (layoutQ.data ? buildIndex(layoutQ.data) : null), [layoutQ.data])
  const siteBounds = useMemo<Bounds | null>(() => {
    const b = layoutQ.data?.bbox
    return b
      ? [
          [b[0], b[1]],
          [b[2], b[3]],
        ]
      : null
  }, [layoutQ.data])

  const raw = Number(params.get('asset'))
  const selected = ix && ix.byId.has(raw) ? raw : null

  const hl = useMemo<Highlight>(() => {
    if (!ix || selected === null) return { selected: null, trace: null, down: null }
    return {
      selected,
      trace: showTrace ? traceUpstream(ix, selected) : null,
      down: descendants(ix, selected),
    }
  }, [ix, selected, showTrace])

  const path = useMemo(() => (ix && selected !== null ? ancestors(ix, selected) : []), [ix, selected])

  const select = useCallback(
    (id: number | null) =>
      setParams(
        (p) => {
          const n = new URLSearchParams(p)
          if (id === null) n.delete('asset')
          else n.set('asset', String(id))
          return n
        },
        { replace: true },
      ),
    [setParams],
  )

  const zoomTo = useCallback(
    (id: number) => {
      const b = ix && assetBounds(ix, id)
      if (b) setFocus((f) => ({ bounds: b, maxZoom: 19.5, n: (f?.n ?? 0) + 1 }))
    },
    [ix],
  )

  const selectAndZoom = useCallback(
    (id: number) => {
      select(id)
      zoomTo(id)
    },
    [select, zoomTo],
  )

  const counts = ix && {
    inverters: ix.byType.inverter.length,
    tables: ix.byType.table.length,
  }

  return (
    <div className="flex h-screen flex-col bg-stone-50 text-stone-900">
      <header className="flex items-center gap-4 border-b border-stone-300 bg-white px-4 py-2">
        <Link to="/" className="text-sm text-stone-500 hover:text-stone-900">
          ← Sites
        </Link>
        <h1 className="text-lg font-semibold">{siteCode}</h1>
        {site && <p className="text-sm text-stone-600">{site.name}</p>}
        {counts && (
          <p className="text-sm text-stone-500">
            {site?.capacity_dc_kwp ? `${(site.capacity_dc_kwp / 1000).toFixed(1)} MWp · ` : ''}
            {counts.inverters} inverters · {counts.tables.toLocaleString()} tables
          </p>
        )}
        <span className="ml-auto rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
          Synthetic layout below inverter level
        </span>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-72 shrink-0 flex-col border-r border-stone-300 bg-white">
          <div className="border-b border-stone-200 p-3">
            <LayerPanel zoom={zoom} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <p className="mb-1 text-[11px] font-semibold tracking-wide text-stone-500 uppercase">
              Assets
            </p>
            {treeQ.data && (
              <AssetTree nodes={treeQ.data} selected={selected} path={path} onSelect={selectAndZoom} />
            )}
          </div>
        </aside>

        <main className="relative min-w-0 flex-1">
          {layoutQ.isPending && <p className="p-6 text-stone-500">Loading layout…</p>}
          {layoutQ.isError && (
            <p className="p-6 text-red-700">Could not load layout: {String(layoutQ.error)}</p>
          )}
          {ix && siteBounds && layoutQ.data && (
            <PlantMap
              ix={ix}
              siteBounds={siteBounds}
              layoutVersion={layoutQ.data.version}
              hl={hl}
              focus={focus}
              onSelect={select}
              onZoom={setZoom}
            />
          )}
          {selected !== null && (
            <div className="pointer-events-none absolute bottom-3 left-3 flex gap-3 rounded bg-white/90 px-3 py-1.5 text-xs shadow">
              <span className="flex items-center gap-1.5">
                <i className="h-2.5 w-2.5 rounded-sm" style={swatch(COLORS.trace)} /> selected + upstream
                path
              </span>
              <span className="flex items-center gap-1.5">
                <i className="h-2.5 w-2.5 rounded-sm" style={swatch(COLORS.downstream)} /> fed by it
              </span>
            </div>
          )}
          <p className="pointer-events-none absolute right-3 bottom-3 rounded bg-white/80 px-2 py-0.5 text-[11px] text-stone-500 tabular-nums">
            zoom {zoom.toFixed(1)}
          </p>
        </main>

        {selected !== null && (
          <AssetDrawer
            assetId={selected}
            onSelect={selectAndZoom}
            onZoom={() => zoomTo(selected)}
            onClose={() => select(null)}
          />
        )}
      </div>
    </div>
  )
}
