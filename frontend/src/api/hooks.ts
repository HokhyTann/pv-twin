import { useQuery } from '@tanstack/react-query'
import type { AssetDetail, SiteLayout, SiteSummary, TreeNode } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`/api/v1${path}`)
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = ((await r.json()) as { detail?: string }).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, detail)
  }
  return (await r.json()) as T
}

export const useSites = () =>
  useQuery({ queryKey: ['sites'], queryFn: () => getJson<SiteSummary[]>('/sites') })

// Geometry only changes when the layout is regenerated; the browser revalidates with the
// ETag, so a long staleTime here just avoids needless refetches within a session.
export const useLayout = (siteCode: string) =>
  useQuery({
    queryKey: ['layout', siteCode],
    queryFn: () => getJson<SiteLayout>(`/sites/${encodeURIComponent(siteCode)}/layout`),
    staleTime: 10 * 60_000,
  })

export const useTree = (siteCode: string) =>
  useQuery({
    queryKey: ['tree', siteCode],
    queryFn: () => getJson<TreeNode[]>(`/sites/${encodeURIComponent(siteCode)}/tree`),
    staleTime: 10 * 60_000,
  })

export const useAsset = (assetId: number | null) =>
  useQuery({
    queryKey: ['asset', assetId],
    queryFn: () => getJson<AssetDetail>(`/assets/${assetId}`),
    enabled: assetId !== null,
  })
