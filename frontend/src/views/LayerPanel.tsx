import { COLORS } from '../layers/plantLayers'
import { LAYERS, useTwin, type LayerKey } from '../state/store'

const SWATCH: Partial<Record<LayerKey, readonly number[]>> = {
  fence: COLORS.fenceLine,
  road: COLORS.road,
  block: COLORS.block,
  table: COLORS.table,
  string: COLORS.string,
  dc_string: COLORS.dc_string,
  dc_main: COLORS.dc_main,
  ac: COLORS.ac,
  combiner: COLORS.combiner,
  inverter: COLORS.inverter,
  transformer: COLORS.transformer,
  substation: COLORS.substation,
}

export default function LayerPanel({ zoom }: { zoom: number }) {
  const visible = useTwin((s) => s.visible)
  const toggle = useTwin((s) => s.toggle)
  const groups = new Map<string, LayerKey[]>()
  for (const k of Object.keys(LAYERS) as LayerKey[]) {
    const g = LAYERS[k].group
    groups.set(g, [...(groups.get(g) ?? []), k])
  }
  return (
    <div className="space-y-3">
      {[...groups].map(([group, keys]) => (
        <fieldset key={group}>
          <legend className="mb-1 text-[11px] font-semibold tracking-wide text-stone-500 uppercase">
            {group}
          </legend>
          {keys.map((k) => {
            const min = (LAYERS[k] as { minZoom?: number }).minZoom
            const hidden = min !== undefined && zoom < min
            const c = SWATCH[k]
            return (
              <label
                key={k}
                className="flex cursor-pointer items-center gap-2 py-0.5 text-sm select-none"
              >
                <input
                  type="checkbox"
                  className="accent-stone-700"
                  checked={visible[k]}
                  onChange={() => toggle(k)}
                />
                {c && (
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-sm"
                    style={{ background: `rgb(${c[0]},${c[1]},${c[2]})` }}
                  />
                )}
                <span className={hidden ? 'text-stone-400' : ''}>{LAYERS[k].label}</span>
                {hidden && visible[k] && (
                  <span className="ml-auto text-[11px] text-stone-400">zoom in</span>
                )}
              </label>
            )
          })}
        </fieldset>
      ))}
    </div>
  )
}
