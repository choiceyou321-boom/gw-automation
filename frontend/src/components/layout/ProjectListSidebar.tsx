import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import {
  Search,
  Plus,
  ChevronDown,
  ChevronRight,
  LayoutDashboard,
  Inbox,
  Sparkles,
  FolderClosed,
} from 'lucide-react'

import { fetchPortfolioSummary } from '@/features/projects/api'
import type { PortfolioRow } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

const TOP_VIEWS = [
  { to: '/', label: '포트폴리오', Icon: LayoutDashboard },
  { to: '/inbox', label: '알림', Icon: Inbox },
  { to: '/insights', label: 'AI 인사이트', Icon: Sparkles },
] as const

interface Props {
  selectedProjectId: number | null
  onSelectProject: (id: number | null) => void
}

/**
 * 레거시 /fund 사이드바 정합 — 검색 + 새 프로젝트 + 53건 리스트 + 이전 프로젝트 폴더
 * v7.0: ProjectSelector 셀렉트박스 패턴 폐기, 사이드바에서 직접 선택
 */
export function ProjectListSidebar({ selectedProjectId, onSelectProject }: Props) {
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  const [search, setSearch] = useState('')
  const [archivedOpen, setArchivedOpen] = useState(false)

  const portfolio = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const { active, archived } = useMemo(() => {
    const items = portfolio.data ?? []
    const q = search.trim().toLowerCase()
    const filtered = q ? items.filter((p) => p.name.toLowerCase().includes(q)) : items
    // 이전 프로젝트 = 수금률 100% 이상이거나 status가 'archived' 인 것 (대략)
    const ar: PortfolioRow[] = []
    const ac: PortfolioRow[] = []
    for (const p of filtered) {
      const isArchived =
        (typeof p.status === 'string' && p.status.includes('archived')) ||
        (p.coll_rate ?? 0) >= 100
      if (isArchived) ar.push(p)
      else ac.push(p)
    }
    return { active: ac, archived: ar }
  }, [portfolio.data, search])

  function handleSelect(id: number | null) {
    onSelectProject(id)
    // 전체 뷰가 아니라면 / 로 이동 (각 라우트가 ?p=id 를 받음)
    if (id !== null && (pathname === '/' || pathname === '/inbox' || pathname === '/insights')) {
      navigate({ to: '/overview', search: { p: id } as never })
    }
  }

  return (
    <aside className="flex w-64 flex-col border-r border-stone-200 bg-card">
      {/* 헤더 */}
      <div className="flex items-center gap-2 px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-900 text-white text-[10px] font-semibold">
          GP
        </div>
        <span className="text-sm font-semibold tracking-tight text-stone-900">
          글로우 PM
        </span>
      </div>

      {/* 전체 뷰 */}
      <nav className="flex flex-col gap-0.5 border-b border-stone-200 px-2 py-2">
        {TOP_VIEWS.map((v) => {
          const active =
            v.to === '/'
              ? pathname === '/'
              : pathname.startsWith(v.to)
          const Icon = v.Icon
          return (
            <button
              key={v.to}
              onClick={() => {
                onSelectProject(null)
                navigate({ to: v.to })
              }}
              className={cn(
                'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors text-left',
                active
                  ? 'bg-stone-100 text-stone-900 font-medium'
                  : 'text-stone-600 hover:bg-stone-50 hover:text-stone-900',
              )}
            >
              <Icon size={15} className="shrink-0" />
              {v.label}
            </button>
          )
        })}
      </nav>

      {/* 검색 + 새 프로젝트 */}
      <div className="space-y-2 px-3 py-2 border-b border-stone-200">
        <div className="relative">
          <Search
            size={14}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-stone-400"
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="프로젝트 검색..."
            className="w-full h-8 rounded-md border border-stone-200 bg-white pl-7 pr-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <button
          onClick={() => alert('새 프로젝트 추가는 v7.1에서 — 현재는 챗봇에서 가능')}
          className="flex w-full items-center justify-center gap-1.5 h-8 rounded-md border border-dashed border-stone-300 text-xs text-stone-600 hover:bg-stone-50 hover:text-stone-900 transition-colors"
        >
          <Plus size={13} />
          새 프로젝트
        </button>
      </div>

      {/* 프로젝트 리스트 */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <div className="px-2 pb-1 flex items-center justify-between">
          <p className="text-xs font-medium text-stone-500">프로젝트</p>
          <span className="text-xs text-stone-400 tabular-nums">{active.length}</span>
        </div>
        <ul className="space-y-0.5">
          {portfolio.isLoading && (
            <li className="px-2 py-1 text-xs text-stone-400">로딩...</li>
          )}
          {active.map((p) => (
            <li key={p.id}>
              <button
                onClick={() => handleSelect(p.id)}
                className={cn(
                  'w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                  selectedProjectId === p.id
                    ? 'bg-zinc-900 text-white'
                    : 'text-stone-700 hover:bg-stone-100',
                )}
              >
                <div className="font-medium line-clamp-1">{p.name}</div>
                <div
                  className={cn(
                    'mt-0.5 flex items-center gap-1.5 text-[10px]',
                    selectedProjectId === p.id ? 'text-stone-300' : 'text-stone-500',
                  )}
                >
                  <span>{p.grade || '-'}</span>
                  <span>·</span>
                  <span>수금 {formatPercent(p.coll_rate ?? 0, 0)}</span>
                </div>
              </button>
            </li>
          ))}
          {active.length === 0 && !portfolio.isLoading && (
            <li className="px-2 py-2 text-xs text-stone-400">
              {search ? '검색 결과 없음' : '등록된 프로젝트 없음'}
            </li>
          )}
        </ul>

        {/* 이전 프로젝트 폴더 */}
        {archived.length > 0 && (
          <div className="mt-3 border-t border-stone-200 pt-2">
            <button
              onClick={() => setArchivedOpen((v) => !v)}
              className="flex w-full items-center gap-1.5 px-2 py-1 text-xs text-stone-600 hover:bg-stone-50 rounded-md"
            >
              {archivedOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <FolderClosed size={13} />
              <span className="flex-1 text-left">이전 프로젝트</span>
              <span className="text-stone-400 tabular-nums">{archived.length}</span>
            </button>
            {archivedOpen && (
              <ul className="mt-1 space-y-0.5 pl-4">
                {archived.map((p) => (
                  <li key={p.id}>
                    <button
                      onClick={() => handleSelect(p.id)}
                      className={cn(
                        'w-full rounded-md px-2 py-1 text-left text-xs transition-colors',
                        selectedProjectId === p.id
                          ? 'bg-zinc-900 text-white'
                          : 'text-stone-500 hover:bg-stone-100',
                      )}
                    >
                      <span className="line-clamp-1">{p.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
