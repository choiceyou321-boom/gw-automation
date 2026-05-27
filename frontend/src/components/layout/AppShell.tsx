import { useMemo } from 'react'
import { useRouterState, useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ProjectListSidebar } from './ProjectListSidebar'
import { ProjectTabs } from './ProjectTabs'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'

const PROJECT_TAB_PATHS = [
  '/overview',
  '/schedule',
  '/kanban',
  '/contracts',
  '/vendors',
  '/collections',
  '/payments',
  '/budget-payment',
  '/risks',
]

const NON_PROJECT_PATHS = ['/', '/inbox', '/insights']

/**
 * v7.0 AppShell — 레거시 /fund 사이드바 정합
 * 좌측: ProjectListSidebar (포트폴리오·알림·인사이트 + 프로젝트 53건 + 이전 프로젝트)
 * 상단: 프로젝트 선택된 경우 ProjectTabs (탭 9개)
 * URL: 프로젝트 탭들은 ?p=$id 쿼리스트링으로 선택 프로젝트 식별
 */
export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const searchObj = useRouterState({ select: (s) => s.location.search }) as Record<
    string,
    unknown
  >

  // URL 쿼리스트링에서 ?p=42 읽기
  const selectedProjectId = useMemo(() => {
    const raw = searchObj?.p
    if (typeof raw === 'number') return raw
    if (typeof raw === 'string' && raw) return Number(raw) || null
    return null
  }, [searchObj])

  const portfolio = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const selectedProject = useMemo(
    () => portfolio.data?.find((p) => p.id === selectedProjectId) ?? null,
    [portfolio.data, selectedProjectId],
  )

  function handleSelectProject(id: number | null) {
    // 현재 path 가 탭 path 면 그대로, 비프로젝트 path 면 /overview 로
    const isProjectTab = PROJECT_TAB_PATHS.some((p) => pathname.startsWith(p))
    const target = isProjectTab ? pathname : '/overview'
    navigate({
      to: target,
      search: id ? ({ p: id } as never) : ({} as never),
    })
  }

  const showTabs =
    selectedProjectId !== null &&
    PROJECT_TAB_PATHS.some((p) => pathname.startsWith(p))

  const isNonProjectView = NON_PROJECT_PATHS.includes(pathname)

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <ProjectListSidebar
        selectedProjectId={selectedProjectId}
        onSelectProject={handleSelectProject}
      />
      <main className="flex-1 overflow-y-auto bg-background flex flex-col">
        {showTabs && selectedProjectId !== null && (
          <ProjectTabs
            projectId={selectedProjectId}
            projectName={selectedProject?.name}
          />
        )}
        <div className="p-6 flex-1">
          {!isNonProjectView && selectedProjectId === null && (
            <div className="rounded-md border border-dashed border-stone-300 p-8 text-center text-sm text-stone-500">
              왼쪽 사이드바에서 프로젝트를 선택하세요.
            </div>
          )}
          {(isNonProjectView || selectedProjectId !== null) && children}
        </div>
      </main>
    </div>
  )
}
