import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { KpiWidget } from './KpiWidget'
import { ProjectCard } from './ProjectCard'
import { fetchPortfolioSummary, fetchNotifications } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatPercent } from '@/lib/format'

type FilterKey = 'all' | 'profitable' | 'loss' | 'high-coll' | 'low-coll'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'profitable', label: '흑자' },
  { key: 'loss', label: '적자' },
  { key: 'high-coll', label: '수금 90%↑' },
  { key: 'low-coll', label: '수금 50%↓' },
]

export function DashboardPage() {
  const [filter, setFilter] = useState<FilterKey>('all')
  const [search, setSearch] = useState('')

  const portfolio = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })
  const notifications = useQuery({
    queryKey: queryKeys.notifications.all,
    queryFn: fetchNotifications,
    staleTime: 10 * 1000,
  })

  const rows = portfolio.data ?? []
  const filtered = useMemo(() => {
    let arr = rows
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      arr = arr.filter((r) => r.name.toLowerCase().includes(q))
    }
    switch (filter) {
      case 'profitable':
        return arr.filter((r) => (r.profit_rate ?? 0) > 0)
      case 'loss':
        return arr.filter((r) => (r.profit_rate ?? 0) < 0)
      case 'high-coll':
        return arr.filter((r) => (r.coll_rate ?? 0) >= 90)
      case 'low-coll':
        return arr.filter((r) => (r.coll_rate ?? 0) < 50)
      default:
        return arr
    }
  }, [rows, filter, search])

  const totals = useMemo(() => {
    if (!rows.length) return null
    const sum = rows.reduce(
      (acc, r) => {
        acc.order += r.total_order ?? 0
        acc.budget += r.execution_budget ?? 0
        acc.coll += r.coll_collected ?? 0
        acc.paid += r.total_paid ?? 0
        acc.collTotal += r.coll_total ?? 0
        acc.payLimit += r.payment_limit ?? 0
        if ((r.profit_rate ?? 0) > 0) acc.positive += 1
        if ((r.profit_rate ?? 0) < 0) acc.negative += 1
        return acc
      },
      { order: 0, budget: 0, coll: 0, paid: 0, collTotal: 0, payLimit: 0, positive: 0, negative: 0 },
    )
    return {
      ...sum,
      collRate: sum.collTotal ? (sum.coll / sum.collTotal) * 100 : 0,
      paidRate: sum.payLimit ? (sum.paid / sum.payLimit) * 100 : 0,
    }
  }, [rows])

  const unread = notifications.data?.filter((n) => !n.read).length ?? 0

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">대시보드</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            전체 프로젝트 포트폴리오 KPI + 53건 카드 그리드
          </p>
        </div>
        {unread > 0 && (
          <Badge variant="warning" className="text-sm">
            읽지 않은 알림 {unread}건
          </Badge>
        )}
      </header>

      {/* KPI 위젯 5종 */}
      <section className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {portfolio.isLoading || !totals ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-28" />)
        ) : (
          <>
            <KpiWidget title="총 프로젝트" value={rows.length} hint="활성 + 완료" />
            <KpiWidget title="총 수주액" value={formatKRW(totals.order)} hint="설계+시공" />
            <KpiWidget title="실행예산 합" value={formatKRW(totals.budget)} />
            <KpiWidget
              title="수금률"
              value={formatPercent(totals.collRate, 1)}
              hint={`${formatKRW(totals.coll)} / ${formatKRW(totals.collTotal)}`}
              tone={totals.collRate >= 80 ? 'positive' : totals.collRate >= 50 ? 'default' : 'warning'}
            />
            <KpiWidget
              title="흑자/적자"
              value={`${totals.positive} / ${totals.negative}`}
              hint="이익률 기준"
            />
          </>
        )}
      </section>

      {/* 필터 + 검색 */}
      <section className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Button
            key={f.key}
            variant={filter === f.key ? 'default' : 'outline'}
            size="sm"
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </Button>
        ))}
        <div className="ml-auto">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="프로젝트명 검색"
            className="h-9 w-64 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <span className="text-sm text-muted-foreground">{filtered.length}건</span>
      </section>

      {/* 카드 그리드 */}
      {portfolio.isLoading ? (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-48" />
          ))}
        </section>
      ) : portfolio.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          포트폴리오 로드 실패: {(portfolio.error as Error).message}
        </div>
      ) : (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((row) => (
            <ProjectCard key={row.id} row={row} />
          ))}
          {filtered.length === 0 && (
            <p className="col-span-full text-center text-sm text-muted-foreground">
              조건에 맞는 프로젝트가 없습니다.
            </p>
          )}
        </section>
      )}
    </div>
  )
}
