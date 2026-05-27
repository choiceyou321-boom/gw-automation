import { useQuery } from '@tanstack/react-query'

import { fetchPortfolioSummary } from '@/features/projects/api'
import { queryKeys } from '@/lib/query-keys'

interface Props {
  value: number | null
  onChange: (id: number | null) => void
  /** 'all' 옵션 노출 여부 */
  includeAll?: boolean
  className?: string
}

/**
 * 53건 프로젝트 셀렉터 — v5.6/v5.4 등 다수 페이지에서 재사용.
 * portfolio-summary 캐시 공유 (staleTime 60s).
 */
export function ProjectSelector({ value, onChange, includeAll = true, className }: Props) {
  const projects = useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
  })

  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className={
        className ??
        'h-9 w-72 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
      }
    >
      {includeAll && <option value="">전체 프로젝트</option>}
      {projects.isLoading && <option>로딩...</option>}
      {projects.data?.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  )
}
