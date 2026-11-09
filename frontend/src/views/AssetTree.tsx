import { useEffect, useMemo, useRef, useState } from 'react'
import type { AssetType, TreeNode } from '../api/types'

const DOT: Record<AssetType, string> = {
  substation: 'bg-[#5b4a8a]',
  meter: 'bg-[#f5d142]',
  transformer: 'bg-[#c0392b]',
  inverter: 'bg-zinc-900',
  combiner: 'bg-[#d9731f]',
  table: 'bg-[#2f5d8a]',
  string: 'bg-[#5684b2]',
}

type Props = {
  nodes: TreeNode[]
  selected: number | null
  /** selected asset's ancestors (nearest first), used to expand and mark the path */
  path: number[]
  onSelect: (id: number) => void
}

export default function AssetTree({ nodes, selected, path, onSelect }: Props) {
  const { roots, kids } = useMemo(() => {
    const kids = new Map<number, TreeNode[]>()
    const roots: TreeNode[] = []
    for (const n of nodes) {
      if (n.parent_id === null) roots.push(n)
      else kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n])
    }
    return { roots, kids }
  }, [nodes])

  // Start with the top levels open, plus the path to a selection that came in via the URL.
  const [open, setOpen] = useState<Set<number>>(
    () =>
      new Set([
        ...nodes
          .filter((n) => n.asset_type === 'substation' || n.asset_type === 'meter')
          .map((n) => n.asset_id),
        ...path,
      ]),
  )

  // Expand down to the selection whenever it changes (state adjusted during render,
  // see react.dev "Adjusting some state when a prop changes").
  const [prevPath, setPrevPath] = useState(path)
  if (path !== prevPath) {
    setPrevPath(path)
    if (path.length) setOpen((o) => new Set([...o, ...path]))
  }

  // Nearest node shown in the tree (tables/strings are not in it).
  const marked = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.asset_id))
    return [selected, ...path].find((id) => id !== null && ids.has(id)) ?? null
  }, [nodes, selected, path])

  const markedRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    markedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [marked])

  const render = (n: TreeNode, depth: number) => {
    const children = kids.get(n.asset_id) ?? []
    const isOpen = open.has(n.asset_id)
    const isMarked = n.asset_id === marked
    return (
      <li key={n.asset_id}>
        <div className="flex items-center" style={{ paddingLeft: depth * 12 }}>
          <button
            type="button"
            aria-label={isOpen ? 'Collapse' : 'Expand'}
            className={`w-4 text-xs text-stone-400 ${children.length ? '' : 'invisible'}`}
            onClick={() =>
              setOpen((o) => {
                const s = new Set(o)
                if (s.has(n.asset_id)) s.delete(n.asset_id)
                else s.add(n.asset_id)
                return s
              })
            }
          >
            {isOpen ? '▾' : '▸'}
          </button>
          <button
            type="button"
            ref={isMarked ? markedRef : undefined}
            onClick={() => onSelect(n.asset_id)}
            className={`flex min-w-0 flex-1 items-center gap-1.5 rounded px-1.5 py-0.5 text-left text-sm ${
              isMarked ? 'bg-[#d62878] text-white' : 'hover:bg-stone-200'
            }`}
          >
            <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[n.asset_type]}`} />
            <span className="truncate">{n.code}</span>
            {n.asset_type === 'inverter' && (
              <span className={`ml-auto text-[11px] ${isMarked ? 'text-white/80' : 'text-stone-400'}`}>
                {n.n_children} CB
              </span>
            )}
          </button>
        </div>
        {isOpen && children.length > 0 && <ul>{children.map((c) => render(c, depth + 1))}</ul>}
      </li>
    )
  }

  return <ul className="text-stone-800">{roots.map((r) => render(r, 0))}</ul>
}
