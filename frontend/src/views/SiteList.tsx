import { Link } from 'react-router'
import { useSites } from '../api/hooks'

const DATASET: Record<string, string> = {
  low: 'site daily · PR check',
  medium: 'site daily · energy model',
  high: 'inverter daily · failure risk',
  expert: '15-min SCADA + meter',
}

export default function SiteList() {
  const q = useSites()
  return (
    <div className="min-h-screen bg-stone-50 text-stone-900">
      <div className="mx-auto max-w-5xl p-8">
        <h1 className="text-2xl font-semibold">PV Digital Twin</h1>
        <p className="mt-1 text-stone-500">Choose a site to open its plant view.</p>
        {q.isError && <p className="mt-6 text-red-700">Could not load sites: {String(q.error)}</p>}
        <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {q.data?.map((s) => (
            <li key={s.site_id}>
              <Link
                to={`/sites/${s.site_code}`}
                className="block rounded-lg border border-stone-200 bg-white p-4 transition hover:border-stone-400 hover:shadow-sm"
              >
                <p className="font-semibold">{s.site_code}</p>
                <p className="text-sm text-stone-600">{s.name}</p>
                <p className="mt-2 text-sm tabular-nums">
                  {s.capacity_dc_kwp ? `${(s.capacity_dc_kwp / 1000).toFixed(1)} MWp` : '—'} ·{' '}
                  {s.n_inverters} inverters
                </p>
                <p className="mt-1 text-xs text-stone-500">{DATASET[s.source_dataset]}</p>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
