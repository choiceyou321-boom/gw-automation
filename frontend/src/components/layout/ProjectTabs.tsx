import { useRouterState, Link } from '@tanstack/react-router'
import { cn } from '@/lib/utils'

const TABS = [
  { to: '/overview', label: '개요' },
  { to: '/schedule', label: '일정' },
  { to: '/kanban', label: '칸반' },
  { to: '/contracts', label: '계약' },
  { to: '/vendors', label: '하도급' },
  { to: '/collections', label: '수금' },
  { to: '/payments', label: '이체' },
  { to: '/budget-payment', label: '예산집행' },
  { to: '/risks', label: '리스크' },
] as const

interface Props {
  projectId: number
  projectName?: string
}

/**
 * 선택된 프로젝트의 상단 탭바.
 * 탭 이동 시 ?p=$projectId 쿼리스트링 유지.
 */
export function ProjectTabs({ projectId, projectName }: Props) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  return (
    <div className="border-b border-stone-200 bg-card">
      {projectName && (
        <div className="px-6 pt-4 pb-2">
          <h2 className="text-lg font-semibold tracking-tight">{projectName}</h2>
        </div>
      )}
      <nav className="flex gap-0 px-4 overflow-x-auto">
        {TABS.map((t) => {
          const active = pathname.startsWith(t.to)
          return (
            <Link
              key={t.to}
              to={t.to}
              search={{ p: projectId } as never}
              className={cn(
                'relative px-3 py-2.5 text-sm whitespace-nowrap transition-colors',
                active
                  ? 'text-stone-900 font-medium'
                  : 'text-stone-500 hover:text-stone-900',
              )}
            >
              {t.label}
              {active && (
                <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-zinc-900" />
              )}
            </Link>
          )
        })}
      </nav>
    </div>
  )
}
