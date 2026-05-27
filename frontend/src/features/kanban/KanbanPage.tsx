import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { KanbanBoardView } from './KanbanBoard'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { Badge } from '@/components/ui/badge'

export function KanbanPage() {
  const projects = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })
  const [projectId, setProjectId] = useState<number | 'all'>('all')

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">칸반</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            할일 286건 — 드래그&드롭으로 상태 변경
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">전체/프로젝트 필터</Badge>
          <select
            value={projectId === 'all' ? '' : projectId}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : 'all')}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">전체 프로젝트</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      </header>

      <KanbanBoardView projectId={projectId === 'all' ? undefined : projectId} />
    </div>
  )
}
