import { api } from '@/lib/api-client'

/** /api/pm/projects/{id}/risks 응답 1건 (project_risk_log 테이블) */
export interface Risk {
  id: number
  project_id: number
  risk_date?: string
  risk_type?: string
  severity?: 'high' | 'medium' | 'low'
  title: string
  description?: string
  impact?: string
  mitigation?: string
  resolved_date?: string
  status?: string
  created_by?: string
  created_at: string
  updated_at?: string
  [k: string]: unknown
}

export interface RisksResult {
  risks: Risk[]
  count: number
}

export function fetchRisks(projectId: number, status?: string): Promise<Risk[]> {
  const params = new URLSearchParams()
  if (status) params.append('status', status)
  const query = params.toString()
  const url = `/api/pm/projects/${projectId}/risks${query ? '?' + query : ''}`
  return api.get<RisksResult>(url).then((r) => r.risks)
}

/** 전체 프로젝트의 리스크 통합 조회 */
export function fetchAllRisks(projectIds: number[], status?: string): Promise<Risk[]> {
  return Promise.all(projectIds.map((id) => fetchRisks(id, status)))
    .then((results) => results.flat())
}
