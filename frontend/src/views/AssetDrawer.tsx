import { useAsset } from '../api/hooks'
import type { AssetType } from '../api/types'
import { useTwin } from '../state/store'

const TYPE_LABEL: Record<AssetType, string> = {
  substation: 'Substation',
  meter: 'Revenue meter',
  transformer: 'MV transformer',
  inverter: 'Central inverter',
  combiner: 'Combiner box',
  table: 'Panel table',
  string: 'PV string',
}

const CHILD_LABEL: Record<AssetType, string> = {
  substation: 'substations',
  meter: 'meters',
  transformer: 'transformers',
  inverter: 'inverters',
  combiner: 'combiner boxes',
  table: 'tables',
  string: 'strings',
}

// Display name + unit per attribute key; unknown keys fall back to a readable form.
const ATTR: Record<string, [string, string?]> = {
  model: ['Model'],
  rated_ac_kw: ['Rated AC power', 'kW'],
  dc_kwp: ['DC capacity', 'kWp'],
  kwp: ['DC capacity', 'kWp'],
  commissioned: ['Commissioned'],
  n_tables: ['Tables'],
  n_strings: ['Strings'],
  modules: ['Modules'],
  tilt_deg: ['Tilt', '°'],
  azimuth_deg: ['Azimuth', '°'],
  rating_kva: ['Rating', 'kVA'],
  voltage_kv: ['Voltage', 'kV'],
  station: ['Station'],
  side: ['Side of corridor'],
  row: ['Row'],
  col: ['Column'],
  role: ['Role'],
  counterparty: ['Counterparty'],
  accuracy_class: ['Accuracy class'],
  dc_kwp_source: ['DC size source'],
}
const HIDDEN = new Set(['generated'])
const ATTR_ORDER = Object.keys(ATTR)
const order = (k: string) => {
  const i = ATTR_ORDER.indexOf(k)
  return i === -1 ? ATTR_ORDER.length : i
}

function fmt(v: unknown, unit?: string): string {
  if (typeof v === 'number') {
    const n = Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 })
    return unit ? `${n} ${unit}` : n
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

const label = (k: string) => ATTR[k]?.[0] ?? k.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase())

const SYNTHETIC: AssetType[] = ['substation', 'transformer', 'combiner', 'table', 'string']

type Props = {
  assetId: number
  onSelect: (id: number) => void
  onZoom: () => void
  onClose: () => void
}

export default function AssetDrawer({ assetId, onSelect, onZoom, onClose }: Props) {
  const q = useAsset(assetId)
  const showTrace = useTwin((s) => s.showTrace)
  const setShowTrace = useTwin((s) => s.setShowTrace)
  const a = q.data

  return (
    <aside className="flex h-full w-96 shrink-0 flex-col border-l border-stone-300 bg-white">
      <header className="flex items-start gap-2 border-b border-stone-200 p-4">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium tracking-wide text-stone-500 uppercase">
            {a ? TYPE_LABEL[a.asset_type] : 'Asset'}
          </p>
          <h2 className="truncate text-xl font-semibold">{a?.code ?? '…'}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded p-1 text-stone-500 hover:bg-stone-100"
        >
          ✕
        </button>
      </header>

      {q.isError && <p className="p-4 text-sm text-red-700">Could not load asset: {String(q.error)}</p>}

      {a && (
        <div className="flex-1 space-y-5 overflow-y-auto p-4 text-sm">
          {/* breadcrumb, substation first */}
          <nav aria-label="Electrical path" className="flex flex-wrap items-center gap-1 text-xs">
            {[...a.ancestors].reverse().map((p) => (
              <span key={p.asset_id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onSelect(p.asset_id)}
                  className="rounded bg-stone-100 px-1.5 py-0.5 hover:bg-stone-200"
                >
                  {p.code}
                </button>
                <span className="text-stone-400">›</span>
              </span>
            ))}
            <span className="rounded bg-[#d62878] px-1.5 py-0.5 text-white">{a.code}</span>
          </nav>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={onZoom}
              className="rounded border border-stone-300 px-3 py-1.5 hover:bg-stone-50"
            >
              Zoom to
            </button>
            <label className="flex cursor-pointer items-center gap-2 rounded border border-stone-300 px-3 py-1.5 select-none">
              <input
                type="checkbox"
                className="accent-[#d62878]"
                checked={showTrace}
                onChange={(e) => setShowTrace(e.target.checked)}
              />
              Trace upstream
            </label>
          </div>

          {(SYNTHETIC.includes(a.asset_type) || a.attrs.generated === true) && (
            <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-900">
              Synthetic asset: generated layout, not from site records.
            </p>
          )}

          <section>
            <h3 className="mb-1.5 font-semibold">Attributes</h3>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
              <dt className="text-stone-500">Site</dt>
              <dd>
                {a.site_code} · {a.site_name}
              </dd>
              {Object.entries(a.attrs)
                .filter(([k]) => !HIDDEN.has(k))
                .sort(([x], [y]) => order(x) - order(y))
                .map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-stone-500">{label(k)}</dt>
                    <dd className="break-words">{fmt(v, ATTR[k]?.[1])}</dd>
                  </div>
                ))}
              {a.lat !== null && a.lon !== null && (
                <>
                  <dt className="text-stone-500">Location</dt>
                  <dd className="tabular-nums">
                    {a.lat.toFixed(5)}, {a.lon.toFixed(5)}
                  </dd>
                </>
              )}
            </dl>
          </section>

          {(Object.keys(a.children).length > 0 || a.downstream_dc_kwp) && (
            <section>
              <h3 className="mb-1.5 font-semibold">Feeds</h3>
              <ul className="space-y-0.5">
                {Object.entries(a.children).map(([t, n]) => (
                  <li key={t}>
                    {n} {CHILD_LABEL[t as AssetType]}
                  </li>
                ))}
                {a.downstream_dc_kwp ? (
                  <li>{fmt(Math.round(a.downstream_dc_kwp))} kWp of panels in total</li>
                ) : null}
              </ul>
            </section>
          )}

          <section>
            <h3 className="mb-1.5 font-semibold">Maintenance log</h3>
            {a.events.length === 0 ? (
              <p className="text-stone-500">No entries.</p>
            ) : (
              <ol className="space-y-2">
                {a.events.map((e, i) => (
                  <li key={i} className="border-l-2 border-stone-300 pl-2">
                    <p className="text-xs text-stone-500">
                      {e.day} · {e.category}
                      {e.scope !== a.code && ` · ${e.scope}`}
                    </p>
                    <p>{e.note}</p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}
    </aside>
  )
}
