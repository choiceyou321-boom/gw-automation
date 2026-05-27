import { api } from '@/lib/api-client'

/** /api/pm/projects/{id}/subcontracts 응답 1건 */
export interface Subcontract {
  id: number
  project_id: number
  company_name: string
  trade_name: string
  contract_amount: number
  progress_1: number
  progress_2: number
  progress_3: number
  progress_4: number
  remaining_amount: number
  progress_rate: number
  [k: string]: unknown
}

export interface SubcontractResult {
  subcontracts: Subcontract[]
}

export function fetchSubcontracts(projectId: number): Promise<Subcontract[]> {
  return api
    .get<SubcontractResult>(`/api/pm/projects/${projectId}/subcontracts`)
    .then((r) => r.subcontracts)
}

/** 전체 프로젝트의 하도급 통합 조회 — portfolio에서 project id들을 얻어 병렬 요청 */
export function fetchAllSubcontracts(projectIds: number[]): Promise<Subcontract[]> {
  return Promise.all(projectIds.map((id) => fetchSubcontracts(id)))
    .then((results) => results.flat())
}
