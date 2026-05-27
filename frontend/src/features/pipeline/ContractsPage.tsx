import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { ProjectSelector } from '@/components/ProjectSelector'
import { fetchSubcontracts } from './api'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatPercent } from '@/lib/format'

function sumPayments(s: Awaited<ReturnType<typeof fetchSubcontracts>>[number]): number {
  return (
    (s.payment_1_confirmed ? s.payment_1 ?? 0 : 0) +
    (s.payment_2_confirmed ? s.payment_2 ?? 0 : 0) +
    (s.payment_3_confirmed ? s.payment_3 ?? 0 : 0) +
    (s.payment_4_confirmed ? s.payment_4 ?? 0 : 0)
  )
}

export function ContractsPage() {
  const projects = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const [projectId, setProjectId] = useState<number | null>(null)
  const activeId = projectId ?? projects.data?.[0]?.id ?? null

  const subs = useQuery({
    queryKey: activeId ? ['subcontracts', 'project', activeId] : ['subcontracts', 'none'],
    queryFn: () => fetchSubcontracts(activeId!),
    enabled: !!activeId,
  })

  const totals = useMemo(() => {
    const items = subs.data ?? []
    const contract = items.reduce((a, s) => a + (s.contract_amount ?? 0), 0)
    const paid = items.reduce((a, s) => a + sumPayments(s), 0)
    return { contract, paid, rate: contract ? (paid / contract) * 100 : 0 }
  }, [subs.data])

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">하도급 계약</h1>
          <p className="mt-1 text-sm text-muted-foreground">프로젝트별 하도급 + 기성 진행률</p>
        </div>
        <ProjectSelector value={activeId} onChange={setProjectId} includeAll={false} />
      </header>

      <div className="grid grid-cols-3 gap-3 text-sm">
        <Stat label="계약 합계" value={formatKRW(totals.contract)} />
        <Stat label="기성 누계" value={formatKRW(totals.paid)} />
        <Stat label="진행률" value={formatPercent(totals.rate, 1)} accent />
      </div>

      {subs.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : subs.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          하도급 로드 실패: {(subs.error as Error).message}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">공종</th>
                <th className="px-4 py-2 text-left font-medium">업체</th>
                <th className="px-4 py-2 text-right font-medium">계약금액</th>
                <th className="px-4 py-2 text-right font-medium">1차</th>
                <th className="px-4 py-2 text-right font-medium">2차</th>
                <th className="px-4 py-2 text-right font-medium">3차</th>
                <th className="px-4 py-2 text-right font-medium">4차</th>
                <th className="px-4 py-2 text-right font-medium">진행</th>
              </tr>
            </thead>
            <tbody>
              {(subs.data ?? []).map((s) => {
                const paid = sumPayments(s)
                const total = s.contract_amount ?? 0
                const rate = total ? (paid / total) * 100 : 0
                return (
                  <tr key={s.id} className="border-t hover:bg-accent/30">
                    <td className="px-4 py-2">{s.trade_name ?? '-'}</td>
                    <td className="px-4 py-2 font-medium">{s.vendor_name ?? '-'}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatKRW(total)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <PayCell v={s.payment_1} ok={!!s.payment_1_confirmed} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <PayCell v={s.payment_2} ok={!!s.payment_2_confirmed} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <PayCell v={s.payment_3} ok={!!s.payment_3_confirmed} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <PayCell v={s.payment_4} ok={!!s.payment_4_confirmed} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Badge variant={rate >= 100 ? 'success' : rate >= 50 ? 'default' : 'secondary'}>
                        {formatPercent(rate, 0)}
                      </Badge>
                    </td>
                  </tr>
                )
              })}
              {(subs.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-muted-foreground">
                    등록된 하도급이 없습니다.
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

function PayCell({ v, ok }: { v?: number; ok: boolean }) {
  if (!v) return <span className="text-muted-foreground">-</span>
  return <span className={ok ? 'text-emerald-600' : 'text-muted-foreground'}>{formatKRW(v)}</span>
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
