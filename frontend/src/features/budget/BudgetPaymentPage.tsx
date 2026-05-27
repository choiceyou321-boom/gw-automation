import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { fetchAllBudgets } from '@/features/budget/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

type SortKey = 'project' | 'budget' | 'rate'
type SortDir = 'asc' | 'desc'

interface ProjectBudgetRow {
  projectId: number
  projectName: string
  totalBudget: number
  totalExecution: number
  executionRate: number
  isOverBudget: boolean
}

export function BudgetPaymentPage() {
  const [sortKey, setSortKey] = useState<SortKey>('project')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  // 포트폴리오 조회
  const { data: portfolio = [], isLoading: isLoadingPortfolio } = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
  })

  const projectMap = useMemo(() => new Map(portfolio.map((p) => [p.id, p.name])), [portfolio])
  const projectIds = useMemo(() => portfolio.map((p) => p.id), [portfolio])

  // 예산 조회
  const { data: allBudgets = [], isLoading: isLoadingBudgets } = useQuery({
    queryKey: queryKeys.budgets,
    queryFn: () => fetchAllBudgets(projectIds),
    enabled: projectIds.length > 0,
  })

  // 프로젝트별 통합
  const rows = useMemo(() => {
    const map = new Map<number, ProjectBudgetRow>()

    allBudgets.forEach((item) => {
      const projectId = item.project_id
      if (!map.has(projectId)) {
        map.set(projectId, {
          projectId,
          projectName: projectMap.get(projectId) || item.project_name || '-',
          totalBudget: 0,
          totalExecution: 0,
          executionRate: 0,
          isOverBudget: false,
        })
      }
      const row = map.get(projectId)!
      row.totalBudget += item.budget_amount ?? 0
      row.totalExecution += item.actual_amount ?? 0
    })

    // 집행률 계산 및 초과 여부 판별
    const result = Array.from(map.values()).map((row) => ({
      ...row,
      executionRate: row.totalBudget > 0 ? (row.totalExecution / row.totalBudget) * 100 : 0,
      isOverBudget: row.totalExecution > row.totalBudget,
    }))

    // 정렬
    result.sort((a, b) => {
      let aVal: unknown = null
      let bVal: unknown = null

      if (sortKey === 'project') {
        aVal = a.projectName
        bVal = b.projectName
      } else if (sortKey === 'budget') {
        aVal = a.totalBudget
        bVal = b.totalBudget
      } else if (sortKey === 'rate') {
        aVal = a.executionRate
        bVal = b.executionRate
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
      }
      const aNum = typeof aVal === 'number' ? aVal : 0
      const bNum = typeof bVal === 'number' ? bVal : 0
      return sortDir === 'asc' ? aNum - bNum : bNum - aNum
    })

    return result
  }, [allBudgets, projectMap, sortKey, sortDir])

  // 전체 합계
  const { totalBudget, totalExecution, totalRate, overBudgetCount } = useMemo(() => {
    const totalBudget = rows.reduce((sum, r) => sum + r.totalBudget, 0)
    const totalExecution = rows.reduce((sum, r) => sum + r.totalExecution, 0)
    const totalRate = totalBudget > 0 ? (totalExecution / totalBudget) * 100 : 0
    const overBudgetCount = rows.filter((r) => r.isOverBudget).length

    return { totalBudget, totalExecution, totalRate, overBudgetCount }
  }, [rows])

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  if (isLoadingPortfolio) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">예산집행</h1>
        <p className="mt-2 text-sm text-muted-foreground">프로젝트별 예산 vs 실행 현황 비교</p>
      </div>

      {/* 요약 카드 */}
      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs font-semibold text-muted-foreground">전체 예산</div>
          <div className="mt-2 text-xl font-bold tabular-nums">{formatKRW(totalBudget)}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs font-semibold text-muted-foreground">전체 실행</div>
          <div className="mt-2 text-xl font-bold tabular-nums">{formatKRW(totalExecution)}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs font-semibold text-muted-foreground">집행률</div>
          <div className="mt-2 text-xl font-bold tabular-nums text-emerald-600">{formatPercent(totalRate, 0)}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs font-semibold text-muted-foreground">초과 프로젝트</div>
          <div className="mt-2 text-xl font-bold tabular-nums text-destructive">{overBudgetCount}건</div>
        </div>
      </div>

      {/* 테이블 */}
      <div className="rounded-lg border bg-card overflow-hidden">
        {isLoadingBudgets ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <div className="px-6 py-8 text-center text-sm text-muted-foreground">예산이 없습니다.</div>
        ) : (
          <>
            {/* 헤더 */}
            <div className="grid gap-4 border-b bg-muted/50 p-4 text-xs font-semibold md:grid-cols-6">
              <div
                className="cursor-pointer hover:underline"
                onClick={() => handleSort('project')}
              >
                프로젝트
                {sortKey === 'project' && <span className="ml-1">{sortDir === 'asc' ? '▲' : '▼'}</span>}
              </div>
              <div className="text-right">예산액</div>
              <div className="text-right">실행액</div>
              <div
                className="text-right cursor-pointer hover:underline"
                onClick={() => handleSort('rate')}
              >
                집행률
                {sortKey === 'rate' && <span className="ml-1">{sortDir === 'asc' ? '▲' : '▼'}</span>}
              </div>
              <div className="col-span-2">진행률 표시</div>
            </div>

            {/* 행 */}
            {rows.map((row, idx) => (
              <div
                key={row.projectId}
                className={cn(
                  'grid gap-4 p-4 text-sm md:grid-cols-6',
                  row.isOverBudget ? 'bg-destructive/5' : '',
                  idx !== rows.length - 1 ? 'border-b' : ''
                )}
              >
                <div>
                  <span className="font-medium">{row.projectName}</span>
                  {row.isOverBudget && (
                    <Badge variant="destructive" className="ml-2 text-xs">
                      초과
                    </Badge>
                  )}
                </div>
                <div className="text-right tabular-nums">{formatKRW(row.totalBudget)}</div>
                <div className={`text-right tabular-nums ${row.isOverBudget ? 'font-bold text-destructive' : ''}`}>
                  {formatKRW(row.totalExecution)}
                </div>
                <div className="text-right tabular-nums font-semibold">{formatPercent(row.executionRate, 0)}</div>

                {/* 진행률 막대 */}
                <div className="col-span-2 flex items-center gap-2">
                  <div className="relative flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        row.executionRate >= 100 ? 'bg-destructive' : 'bg-emerald-500'
                      )}
                      style={{ width: `${Math.min(row.executionRate, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-12 text-right">
                    {row.executionRate > 100
                      ? `+${formatPercent(row.executionRate - 100, 0)}`
                      : formatPercent(row.executionRate, 0)}
                  </span>
                </div>
              </div>
            ))}

            {/* 합계 푸터 */}
            <div className="grid gap-4 border-t bg-muted/30 p-4 text-xs font-semibold md:grid-cols-6">
              <div>합계</div>
              <div className="text-right">{formatKRW(totalBudget)}</div>
              <div className={cn('text-right', totalExecution > totalBudget ? 'text-destructive' : '')}>
                {formatKRW(totalExecution)}
              </div>
              <div className="text-right">{formatPercent(totalRate, 0)}</div>
              <div className="col-span-2" />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
