import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { fetchAllRisks } from '@/features/risks/api'
import { queryKeys } from '@/lib/query-keys'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

export function RisksPage() {
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [unsolvedOnly, setUnsolvedOnly] = useState(false)

  // 포트폴리오 조회
  const { data: portfolio = [], isLoading: isLoadingPortfolio } = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
  })

  const projectMap = useMemo(() => new Map(portfolio.map((p) => [p.id, p.name])), [portfolio])
  const projectIds = useMemo(() => portfolio.map((p) => p.id), [portfolio])

  // 리스크 조회
  const { data: allRisks = [], isLoading: isLoadingRisks } = useQuery({
    queryKey: queryKeys.risks,
    queryFn: () => fetchAllRisks(projectIds),
    enabled: projectIds.length > 0,
  })

  // 필터링
  const filtered = useMemo(() => {
    let result = allRisks

    // 프로젝트 필터
    if (selectedProjectId !== null) {
      result = result.filter((r) => r.project_id === selectedProjectId)
    }

    // 미해결 필터
    if (unsolvedOnly) {
      result = result.filter((r) => r.status !== 'closed' && r.status !== 'resolved')
    }

    // 우선순위 역순 정렬 (high → medium → low)
    const severityOrder = { high: 0, medium: 1, low: 2 }
    result.sort(
      (a, b) =>
        (severityOrder[a.severity] ?? 999) - (severityOrder[b.severity] ?? 999) ||
        (new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    )

    return result
  }, [allRisks, selectedProjectId, unsolvedOnly])

  // 우선순위별 색상
  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'high':
        return 'bg-destructive/10 border-destructive/30 text-destructive'
      case 'medium':
        return 'bg-amber-50 border-amber-300 text-amber-900'
      default:
        return 'bg-blue-50 border-blue-200 text-blue-900'
    }
  }

  const getSeverityBadgeVariant = (severity: string) => {
    switch (severity) {
      case 'high':
        return 'destructive'
      case 'medium':
        return 'secondary'
      default:
        return 'default'
    }
  }

  if (isLoadingPortfolio) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">리스크</h1>
        <p className="mt-2 text-sm text-muted-foreground">프로젝트별 리스크 현황 및 우선순위</p>
      </div>

      {/* 필터 */}
      <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
        {/* 프로젝트 선택 */}
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          <Button
            variant={selectedProjectId === null ? 'default' : 'outline'}
            size="sm"
            onClick={() => setSelectedProjectId(null)}
          >
            전체 ({projectIds.length})
          </Button>
          {portfolio.map((p) => (
            <Button
              key={p.id}
              variant={selectedProjectId === p.id ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSelectedProjectId(p.id)}
              className="shrink-0"
            >
              {p.name}
            </Button>
          ))}
        </div>

        {/* 미해결만 보기 */}
        <Button
          variant={unsolvedOnly ? 'default' : 'outline'}
          size="sm"
          onClick={() => setUnsolvedOnly(!unsolvedOnly)}
        >
          미해결만 ({filtered.filter((r) => r.status !== 'closed' && r.status !== 'resolved').length})
        </Button>
      </div>

      {/* 리스크 카드 그리드 */}
      {isLoadingRisks ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          리스크가 없습니다.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filtered.map((risk) => (
            <div
              key={risk.id}
              className={cn(
                'rounded-lg border-2 p-4 transition-all hover:shadow-md',
                getSeverityColor(risk.severity)
              )}
            >
              {/* 헤더 */}
              <div className="mb-3 flex items-start justify-between">
                <div className="flex-1">
                  <div className="text-xs font-semibold opacity-75">{projectMap.get(risk.project_id) || '-'}</div>
                  <div className="mt-1 text-sm font-semibold">{risk.risk_type || '리스크'}</div>
                </div>
                <Badge variant={getSeverityBadgeVariant(risk.severity)} className="ml-2 shrink-0 text-xs">
                  {risk.severity === 'high' ? '높음' : risk.severity === 'medium' ? '중간' : '낮음'}
                </Badge>
              </div>

              {/* 설명 */}
              <div className="mb-3 text-sm leading-relaxed">{risk.description || '-'}</div>

              {/* 메타 정보 */}
              <div className="space-y-1 border-t pt-3 text-xs opacity-75">
                <div>
                  <span className="font-semibold">작성자:</span> {risk.created_by || '-'}
                </div>
                <div>
                  <span className="font-semibold">작성일:</span> {formatDate(risk.created_at)}
                </div>
                {risk.status && (
                  <div>
                    <span className="font-semibold">상태:</span>{' '}
                    {risk.status === 'open' ? '미해결' : risk.status === 'closed' ? '해결' : risk.status}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
