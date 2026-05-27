import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { fetchPortfolioSummary } from '@/features/projects/api'
import { fetchAllSubcontracts, type Subcontract } from '@/features/vendors/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatPercent } from '@/lib/format'

type SortKey = 'project' | 'trade' | 'remaining'
type SortDir = 'asc' | 'desc'

interface Column {
  key: string
  label: string
  sortable: boolean
  align?: 'left' | 'right'
  render: (row: Subcontract, projects: Map<number, string>) => React.ReactNode
}

const COLUMNS: Column[] = [
  {
    key: 'project',
    label: '프로젝트',
    sortable: true,
    render: (r, projects) => <span className="font-medium">{projects.get(r.project_id) || '-'}</span>,
  },
  {
    key: 'trade',
    label: '공종',
    sortable: false,
    render: (r) => <span className="text-sm">{r.trade_name || '-'}</span>,
  },
  {
    key: 'company',
    label: '업체명',
    sortable: false,
    render: (r) => <span className="text-sm">{r.company_name || '-'}</span>,
  },
  {
    key: 'contract',
    label: '계약금액',
    sortable: false,
    align: 'right',
    render: (r) => <span className="tabular-nums text-sm">{formatKRW(r.contract_amount)}</span>,
  },
  {
    key: 'progress',
    label: '1~4차 기성합계',
    sortable: false,
    align: 'right',
    render: (r) => {
      const total = (r.progress_1 ?? 0) + (r.progress_2 ?? 0) + (r.progress_3 ?? 0) + (r.progress_4 ?? 0)
      return <span className="tabular-nums text-sm">{formatKRW(total)}</span>
    },
  },
  {
    key: 'remaining',
    label: '잔액',
    sortable: true,
    align: 'right',
    render: (r) => {
      const cls = (r.remaining_amount ?? 0) > 0 ? 'text-emerald-600' : 'text-destructive'
      return <span className={`tabular-nums text-sm font-medium ${cls}`}>{formatKRW(r.remaining_amount)}</span>
    },
  },
  {
    key: 'rate',
    label: '진행률',
    sortable: false,
    align: 'right',
    render: (r) => {
      const rate = r.progress_rate ?? 0
      return (
        <Badge variant={rate >= 90 ? 'success' : rate >= 50 ? 'default' : 'secondary'} className="tabular-nums text-xs">
          {formatPercent(rate, 0)}
        </Badge>
      )
    },
  },
]

export function VendorsPage() {
  const [sortKey, setSortKey] = useState<SortKey>('project')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)

  // 포트폴리오 조회
  const { data: portfolio = [], isLoading: isLoadingPortfolio } = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
  })

  const projectMap = useMemo(() => new Map(portfolio.map((p) => [p.id, p.name])), [portfolio])
  const projectIds = useMemo(() => portfolio.map((p) => p.id), [portfolio])

  // 하도급 조회
  const { data: allSubcontracts = [], isLoading: isLoadingSubcontracts } = useQuery({
    queryKey: queryKeys.subcontracts,
    queryFn: () => fetchAllSubcontracts(projectIds),
    enabled: projectIds.length > 0,
  })

  // 필터링 및 정렬
  const filtered = useMemo(() => {
    let result = allSubcontracts
    if (selectedProjectId !== null) {
      result = result.filter((s) => s.project_id === selectedProjectId)
    }

    // 정렬
    result.sort((a, b) => {
      let aVal: unknown = null
      let bVal: unknown = null

      if (sortKey === 'project') {
        aVal = projectMap.get(a.project_id) || ''
        bVal = projectMap.get(b.project_id) || ''
      } else if (sortKey === 'trade') {
        aVal = a.trade_name || ''
        bVal = b.trade_name || ''
      } else if (sortKey === 'remaining') {
        aVal = a.remaining_amount ?? 0
        bVal = b.remaining_amount ?? 0
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
      }
      const aNum = typeof aVal === 'number' ? aVal : 0
      const bNum = typeof bVal === 'number' ? bVal : 0
      return sortDir === 'asc' ? aNum - bNum : bNum - aNum
    })

    return result
  }, [allSubcontracts, selectedProjectId, sortKey, sortDir, projectMap])

  // 합계 계산
  const { totalContract, totalProgress } = useMemo(() => {
    return {
      totalContract: filtered.reduce((sum, s) => sum + (s.contract_amount ?? 0), 0),
      totalProgress: filtered.reduce((sum, s) => {
        return sum + ((s.progress_1 ?? 0) + (s.progress_2 ?? 0) + (s.progress_3 ?? 0) + (s.progress_4 ?? 0))
      }, 0),
    }
  }, [filtered])

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
        <h1 className="text-2xl font-semibold tracking-tight">하도급</h1>
        <p className="mt-2 text-sm text-muted-foreground">프로젝트별 하도급 현황 및 진행률</p>
      </div>

      {/* 필터: 프로젝트 선택 */}
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

      {/* 테이블 */}
      <div className="rounded-lg border bg-card">
        {isLoadingSubcontracts ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-6 py-8 text-center text-sm text-muted-foreground">하도급이 없습니다.</div>
        ) : (
          <>
            {/* 헤더 */}
            <div className="grid gap-2 border-b bg-muted/50 p-4 text-xs font-semibold md:grid-cols-7">
              {COLUMNS.map((col) => (
                <div
                  key={col.key}
                  className={`${col.align === 'right' ? 'text-right' : ''} ${col.sortable ? 'cursor-pointer hover:underline' : ''}`}
                  onClick={() => col.sortable && handleSort(col.key as SortKey)}
                >
                  {col.label}
                  {col.sortable && sortKey === col.key && (
                    <span className="ml-1">{sortDir === 'asc' ? '▲' : '▼'}</span>
                  )}
                </div>
              ))}
            </div>

            {/* 행 */}
            {filtered.map((row, idx) => (
              <div
                key={row.id || idx}
                className={`grid gap-2 p-4 text-sm md:grid-cols-7 ${idx !== filtered.length - 1 ? 'border-b' : ''}`}
              >
                {COLUMNS.map((col) => (
                  <div key={col.key} className={col.align === 'right' ? 'text-right' : ''}>
                    {col.render(row, projectMap)}
                  </div>
                ))}
              </div>
            ))}

            {/* 합계 푸터 */}
            <div className="grid gap-2 border-t bg-muted/30 p-4 text-xs font-semibold md:grid-cols-7">
              <div>합계</div>
              <div />
              <div />
              <div className="text-right">{formatKRW(totalContract)}</div>
              <div className="text-right">{formatKRW(totalProgress)}</div>
              <div className="text-right">{formatKRW(totalContract - totalProgress)}</div>
              <div />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
