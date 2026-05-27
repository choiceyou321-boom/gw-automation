import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { GanttChart } from './GanttChart'
import { fetchProjectSchedule } from './api'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'

const STATUS_LEGEND: { key: string; label: string; cls: string }[] = [
  { key: 'planned', label: '계획', cls: 'bg-stone-300' },
  { key: 'in_progress', label: '진행', cls: 'bg-stone-600' },
  { key: 'done', label: '완료', cls: 'bg-emerald-600' },
  { key: 'blocked', label: '차단', cls: 'bg-stone-400' },
  { key: 'critical', label: 'CP', cls: 'bg-rose-700' },
]

export function SchedulePage() {
  const projects = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const [projectId, setProjectId] = useState<number | null>(null)
  const activeId = projectId ?? projects.data?.[0]?.id ?? null

  const schedule = useQuery({
    queryKey: activeId ? ['schedule', 'project', activeId] : ['schedule', 'none'],
    queryFn: () => fetchProjectSchedule(activeId!),
    enabled: !!activeId,
  })

  const counts = useMemo(() => {
    const items = schedule.data ?? []
    const c: Record<string, number> = {}
    for (const it of items) c[it.status] = (c[it.status] ?? 0) + 1
    return c
  }, [schedule.data])

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">일정표</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            프로젝트별 공정 간트 차트 (schedule_items)
          </p>
        </div>
        <select
          value={activeId ?? ''}
          onChange={(e) => setProjectId(Number(e.target.value) || null)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {projects.isLoading && <option>로딩...</option>}
          {projects.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </header>

      {/* 범례 + 카운트 */}
      <div className="flex flex-wrap items-center gap-3">
        {STATUS_LEGEND.map((s) => (
          <div key={s.key} className="flex items-center gap-1.5 text-xs">
            <span className={`inline-block h-3 w-3 rounded-sm ${s.cls}`} />
            <span className="text-muted-foreground">{s.label}</span>
            {counts[s.key] !== undefined && (
              <Badge variant="outline" className="ml-1">
                {counts[s.key]}
              </Badge>
            )}
          </div>
        ))}
        <div className="ml-auto text-xs text-muted-foreground">
          총 {schedule.data?.length ?? 0}개 항목
        </div>
      </div>

      {schedule.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : schedule.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          일정 로드 실패: {(schedule.error as Error).message}
        </div>
      ) : (
        <GanttChart items={schedule.data ?? []} />
      )}
    </div>
  )
}
