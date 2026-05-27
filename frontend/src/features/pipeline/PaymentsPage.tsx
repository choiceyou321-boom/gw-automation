import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { ProjectSelector } from '@/components/ProjectSelector'
import { ExportButton } from '@/components/ExportButton'
import type { ExportColumn } from '@/lib/export'
import { fetchPayments } from './api'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatDate } from '@/lib/format'

export function PaymentsPage() {
  const projects = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const [projectId, setProjectId] = useState<number | null>(null)
  const activeId = projectId ?? projects.data?.[0]?.id ?? null

  const payments = useQuery({
    queryKey: activeId ? ['payments', 'project', activeId] : ['payments', 'none'],
    queryFn: () => fetchPayments(activeId!),
    enabled: !!activeId,
  })

  const totals = useMemo(() => {
    const items = payments.data ?? []
    const sum = items.reduce((a, p) => a + (p.amount ?? 0), 0)
    return { sum, count: items.length }
  }, [payments.data])

  // 익스포트 컬럼 정의
  const exportColumns: ExportColumn<any>[] = [
    {
      key: 'payment_date',
      label: '이체일',
      format: (row) => formatDate((row as any).payment_date),
    },
    { key: 'vendor_name', label: '업체명' },
    { key: 'amount', label: '금액' },
    { key: 'reference', label: '적요' },
  ]

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">이체 내역</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            GW 이체완료 스크래핑 — payment_history
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExportButton
            rows={payments.data ?? []}
            columns={exportColumns}
            filenameBase="payments"
            title="이체 내역"
            disabled={payments.isLoading}
          />
          <ProjectSelector value={activeId} onChange={setProjectId} includeAll={false} />
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <Stat label="총 이체 합계" value={formatKRW(totals.sum)} />
        <Stat label="총 건수" value={`${totals.count}건`} />
      </div>

      {payments.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : payments.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          이체 로드 실패: {(payments.error as Error).message}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">결재일</th>
                <th className="px-4 py-2 text-left font-medium">이체일</th>
                <th className="px-4 py-2 text-left font-medium">거래처</th>
                <th className="px-4 py-2 text-left font-medium">회계단위</th>
                <th className="px-4 py-2 text-right font-medium">금액</th>
                <th className="px-4 py-2 text-left font-medium">메모</th>
              </tr>
            </thead>
            <tbody>
              {(payments.data ?? []).map((p) => (
                <tr key={p.id} className="border-t hover:bg-accent/30">
                  <td className="px-4 py-2 tabular-nums">{formatDate(p.scheduled_date)}</td>
                  <td className="px-4 py-2 tabular-nums">{formatDate(p.payment_date)}</td>
                  <td className="px-4 py-2">{p.vendor ?? '-'}</td>
                  <td className="px-4 py-2 text-muted-foreground">{p.accounting_unit ?? '-'}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatKRW(p.amount)}</td>
                  <td className="px-4 py-2 text-xs text-muted-foreground line-clamp-1">
                    {p.memo ?? ''}
                  </td>
                </tr>
              ))}
              {(payments.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                    이체 내역이 없습니다.
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
    </div>
  )
}
