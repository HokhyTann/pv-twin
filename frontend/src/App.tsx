import { useEffect, useState } from 'react'

type Health = {
  api: string
  db: string
  postgres: string | null
  extensions: Record<string, string>
  schemas: string[]
  migration: string | null
}

type State =
  | { kind: 'loading' }
  | { kind: 'ok'; health: Health }
  | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    fetch('/api/v1/health')
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        setState({ kind: 'ok', health: (await r.json()) as Health })
      })
      .catch((e: unknown) =>
        setState({ kind: 'error', message: e instanceof Error ? e.message : String(e) }),
      )
  }, [])

  return (
    <main className="shell">
      <h1>PV Digital Twin</h1>
      <p className="muted">Phase 0 · scaffold check</p>

      {state.kind === 'loading' && <p>Checking API…</p>}

      {state.kind === 'error' && (
        <p className="status bad">API unreachable: {state.message}</p>
      )}

      {state.kind === 'ok' && (
        <>
          <p className={`status ${state.health.db === 'ok' ? 'good' : 'bad'}`}>
            API {state.health.api} · DB {state.health.db}
          </p>
          <dl>
            <dt>Postgres</dt>
            <dd>{state.health.postgres ?? '—'}</dd>
            <dt>Extensions</dt>
            <dd>
              {Object.entries(state.health.extensions)
                .map(([k, v]) => `${k} ${v}`)
                .join(' · ') || '—'}
            </dd>
            <dt>Schemas</dt>
            <dd>{state.health.schemas.join(', ') || '—'}</dd>
            <dt>Migration</dt>
            <dd>{state.health.migration ?? 'none applied'}</dd>
          </dl>
        </>
      )}
    </main>
  )
}
