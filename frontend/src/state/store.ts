import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const LAYERS = {
  fence: { label: 'Fence', group: 'Site' },
  road: { label: 'Roads', group: 'Site' },
  block: { label: 'Inverter blocks', group: 'Site' },
  table: { label: 'Panel tables', group: 'PV array' },
  string: { label: 'Strings', group: 'PV array', minZoom: 18 },
  dc_string: { label: 'DC string cables', group: 'Cables', minZoom: 16.5 },
  dc_main: { label: 'DC main cables', group: 'Cables' },
  ac: { label: 'AC LV + MV cables', group: 'Cables' },
  combiner: { label: 'Combiner boxes', group: 'Equipment', minZoom: 16 },
  inverter: { label: 'Inverters', group: 'Equipment' },
  transformer: { label: 'Transformers', group: 'Equipment' },
  substation: { label: 'Substation + meter', group: 'Equipment' },
  labels: { label: 'Labels', group: 'Equipment', minZoom: 17 },
} as const satisfies Record<string, { label: string; group: string; minZoom?: number }>

export type LayerKey = keyof typeof LAYERS

type TwinState = {
  visible: Record<LayerKey, boolean>
  showTrace: boolean
  toggle: (k: LayerKey) => void
  setShowTrace: (v: boolean) => void
}

const allOn = Object.fromEntries(Object.keys(LAYERS).map((k) => [k, true])) as Record<
  LayerKey,
  boolean
>

/** UI preferences for the site twin (persisted). Selection lives in the URL instead. */
export const useTwin = create<TwinState>()(
  persist(
    (set) => ({
      visible: allOn,
      showTrace: true,
      toggle: (k) => set((s) => ({ visible: { ...s.visible, [k]: !s.visible[k] } })),
      setShowTrace: (v) => set({ showTrace: v }),
    }),
    {
      name: 'pv-twin-ui',
      // keep layers added in later versions visible by default
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<TwinState>
        return { ...current, ...p, visible: { ...current.visible, ...(p.visible ?? {}) } }
      },
    },
  ),
)
