import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ExportButton } from '@/components/ExportButton'
import type { ExportColumn } from '@/lib/export'
import { fetchPortfolioSummary } from '@/features/projects/api'
import type { PortfolioRow } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'
import { formatKRW, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

type SortKey = 'name' | 'total_order' | 'profit_rate' | 'coll_rate'
type SortDir = 'asc' | 'desc'

interface Column {
  key: SortKey | string
  label: string
  sortable: boolean
  align?: 'left' | 'right'
  render: (row: PortfolioRow) => React.ReactNode
}

/** 익스포트용 컬럼 정의 (UI 렌더링과 분리 — 순수 문자열/숫자만) */
const EXPORT_COLUMNS: ExportColumn<PortfolioRow>[] = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '프로젝트명' },
  { key: 'grade', label: '등급' },
  { key: 'category', label: '구분' },
  { key: 'total_order', label: '수주액' },
  { key: 'execution_budget', label: '실행예산' },
  { key: 'profit_amount', label: '이익액' },
  { key: 'profit_rate', label: '이익률(%)' },
  { key: 'coll_total', label: '수금예정' },
  { key: 'coll_collected', label: '수금완료' },
  { key: 'coll_rate', label: '수금률(%)' },
  { key: 'payment_limit', label: '지급한도' },
  { key: 'total_paid', label: '지급누계' },
]

const COLUMNS: Column[] = [
  {
    key: 'name',
    label: '프로젝트',
    sortable: true,
    render: (r) => (
      <Link
        to="/projects/$projectId"
        params={{ projectId: String(r.id) }}
        className="font-medium hover:underline"
      >
        {r.name}
      </Link>
    ),
  },
  {
    key: 'grade',
    label: '등급',
    sortable: false,
    render: (r) => <Badge variant="outline">{(r.grade ?? '-').toString()}</Badge>,
  },
  {
    key: 'category',
    label: '구분',
    sortable: false,
    render: (r) => <span className="text-muted-foreground">{r.category ?? '-'}</span>,
  },
  {
    key: 'total_order',
    label: '수주액',
    sortable: true,
    align: 'right',
    render: (r) => <span className="tabular-nums">{formatKRW(r.total_order)}</span>,
  },
  {
    key: 'execution_budget',
    label: '실행예산',
    sortable: false,
    align: 'right',
    render: (r) => <span className="tabular-nums">{formatKRW(r.execution_budget)}</span>,
  },
  {
    key: 'profit_rate',
    label: '이익률',
    sortable: true,
    align: 'right',
    render: (r) => {
      const v = r.profit_rate ?? 0
      const cls = v < 0 ? 'text-destructive' : v > 0 ? 'text-emerald-600' : ''
      return <span className={`tabular-nums font-medium ${cls}`}>{formatPercent(v)}</span>
    },
  },
  {
    key: 'coll_rate',
    label: '수금률',
    sortable: true,
    align: 'right',
    render: (r) => {
      const v = r.coll_rate ?? 0
      return (
        <Badge
          variant={v >= 90 ? 'success' : v >= 50 ? 'default' : 'secondary'}
          className="tabular-nums"
        >
          {formatPercent(v, 0)}
        </Badge>
      )
    },
  },
]

export function OverviewPage() {
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [search, setSearch] = useState('')

  const portfolio = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  const rows = portfolio.data ?? []
  const filtered = useMemo(() => {
    let arr = rows
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      arr = arr.filter((r) => r.name.toLowerCase().includes(q))
    }
    const sorted = [...arr].sort((a, b) => {
      const av = a[sortKey] ?? 0
      const bv = b[sortKey] ?? 0
      let cmp = 0
      if (typeof av === 'string' && typeof bv === 'string') {
        cmp = av.localeCompare(bv, 'ko')
      } else {
        cmp = (Number(av) || 0) - (Number(bv) || 0)
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [rows, sortKey, sortDir, search])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">개요</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            전체 프로젝트 {rows.length}건 — 행 클릭 시 상세
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="프로젝트명 검색"
            className="h-9 w-64 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <ExportButton
            rows={filtered}
            columns={EXPORT_COLUMNS}
            filenameBase={`프로젝트_개요_${new Date().toISOString().slice(0, 10)}`}
            title="프로젝트 개요"
          />
        </div>
      </header>

      {portfolio.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : portfolio.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          로드 실패: {(portfolio.error as Error).message}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className={cn(
                      'px-4 py-2 font-medium',
                      c.align === 'right' ? 'text-right' : 'text-left',
                    )}
                  >
                    {c.sortable ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleSort(c.key as SortKey)}
                        className="-mx-2 h-7 px-2"
                      >
                        {c.label}
                        {sortKey === c.key && (
                          <span className="ml-1 text-xs">{sortDir === 'asc' ? '▲' : '▼'}</span>
                        )}
                      </Button>
                    ) : (
                      c.label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id} className="border-t hover:bg-accent/30">
                  {COLUMNS.map((c) => (
                    <td
                      key={c.key}
                      className={cn('px-4 py-2', c.align === 'right' ? 'text-right' : '')}
                    >
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={COLUMNS.length}
                    className="px-4 py-8 text-center text-sm text-muted-foreground"
                  >
                    검색 결과가 없습니다.
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
