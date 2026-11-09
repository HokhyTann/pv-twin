import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router'
import NotFound from './views/NotFound'
import SiteList from './views/SiteList'

// deck.gl is most of the bundle: load it only when a site is opened.
const SiteTwin = lazy(() => import('./views/SiteTwin'))

export default function App() {
  return (
    <Suspense fallback={<p className="p-6 text-stone-500">Loading…</p>}>
      <Routes>
        <Route path="/" element={<SiteList />} />
        <Route path="/sites/:siteCode" element={<SiteTwin />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
