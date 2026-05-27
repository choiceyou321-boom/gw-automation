import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { ProjectSelector } from '@/components/ProjectSelector'
import { ExportButton } from '@/components/ExportButton'
import type { ExportColumn } from '@/lib/export'
import { fetchCollections } from './api'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatPercent, formatDate } from '@/lib/format'

export function CollectionsPage() {
  const projects = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const [projectId, setProjectId] = useState<number | null>(null)
  const activeId = projectId ?? projects.data?.[0]?.id ?? null

  const cols = useQuery({
    queryKey: activeId ? ['collections', 'project', activeId] : ['collections', 'none'],
    queryFn: () => fetchCollections(activeId!),
    enabled: !!activeId,
  })

  const totals = useMemo(() => {
    const items = cols.data ?? []
    const total = items.reduce((a, c) => a + (c.amount ?? 0), 0)
    const collected = items.reduce(
      (a, c) => a + ((c.collected ? c.amount : 0) ?? 0),
      0,
    )
    return { total, collected, rate: total ? (collected / total) * 100 : 0 }
  }, [cols.data])

  // 익스포트 컬럼 정의
  const exportColumns: ExportColumn<any>[] = [
    {
      key: 'scheduled_date',
      label: '예정일',
      format: (row) => formatDate(row.scheduled_date),
    },
    { key: 'description', label: '내역' },
    { key: 'amount', label: '금액' },
    {
      key: 'collected',
      label: '완료 여부',
      format: (row) => (row.collected ? '완료' : '미완료'),
    },
  ]

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">수금 현황</h1>
          <p className="mt-1 text-sm text-muted-foreground">프로젝트별 수금 일정 + 완료 여부</p>
        </div>
        <div className="flex items-center gap-2">
          <ExportButton
            rows={cols.data ?? []}
            columns={exportColumns}
            filenameBase="collections"
            title="수금 현황"
            disabled={cols.isLoading}
          />
          <ProjectSelector value={activeId} onChange={setProjectId} includeAll={false} />
        </div>
      </header>

      <div className="grid grid-cols-3 gap-3 text-sm">
        <Stat label="총 수금 예정" value={formatKRW(totals.total)} />
        <Stat label="수금 완료" value={formatKRW(totals.collected)} />
        <Stat label="수금률" value={formatPercent(totals.rate, 1)} accent />
      </div>

      {cols.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : cols.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          수금 로드 실패: {(cols.error as Error).message}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">예정일</th>
                <th className="px-4 py-2 text-left font-medium">내역</th>
                <th className="px-4 py-2 text-right font-medium">금액</th>
                <th className="px-4 py-2 text-center font-medium">완료</th>
              </tr>
            </thead>
            <tbody>
              {(cols.data ?? []).map((c) => (
                <tr key={c.id} className="border-t hover:bg-accent/30">
                  <td className="px-4 py-2 tabular-nums">{formatDate(c.scheduled_date)}</td>
                  <td className="px-4 py-2">{c.description ?? '-'}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatKRW(c.amount)}</td>
                  <td className="px-4 py-2 text-center">
                    {c.collected ? (
                      <Badge variant="success">완료</Badge>
                    ) : (
                      <Badge variant="outline">예정</Badge>
                    )}
                  </td>
                </tr>
              ))}
              {(cols.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">
                    등록된 수금이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${accent ? 'text-primary' : ''}`}>
        {value}
      </p>
    </div>
  )
}
