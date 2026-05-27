import { api } from '@/lib/api-client'

/** /api/pm/projects/{id}/budget 응답 1건 (budget_actual 테이블) */
export interface BudgetItem {
  id?: number
  project_id: number
  project_name?: string
  year?: number
  budget_code?: string
  budget_category?: string
  budget_sub_category?: string
  budget_amount: number
  actual_amount: number
  difference?: number
  execution_rate?: number
  scraped_at?: string
  [k: string]: unknown
}

export interface BudgetResult {
  budget: BudgetItem[]
}

export function fetchBudget(projectId: number, year?: number): Promise<BudgetItem[]> {
  const params = new URLSearchParams()
  if (year) params.append('year', year.toString())
  const query = params.toString()
  const url = `/api/pm/projects/${projectId}/budget${query ? '?' + query : ''}`
  return api.get<BudgetResult>(url).then((r) => r.budget)
}

/** 전체 프로젝트의 예산 통합 조회 */
export function fetchAllBudgets(projectIds: number[], year?: number): Promise<BudgetItem[]> {
  return Promise.all(projectIds.map((id) => fetchBudget(id, year)))
    .then((results) => results.flat())
}
