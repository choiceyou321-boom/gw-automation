import { api } from '@/lib/api-client'

/** /api/pm/projects/{id}/subcontracts 응답 1건 */
export interface Subcontract {
  id: number
  project_id: number
  trade_id?: number
  company_name: string
  trade_name?: string
  account_category?: string
  has_estimate?: number
  has_contract?: number
  has_vendor_reg?: number
  estimate_amount?: number
  contract_amount: number
  payment_1?: number
  payment_2?: number
  payment_3?: number
  payment_4?: number
  remaining_amount: number
  payment_rate?: number
  created_at?: string
  updated_at?: string
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

/** 하도급 업체 추가 */
export async function createSubcontract(
  projectId: number,
  data: Omit<Subcontract, 'id' | 'created_at' | 'updated_at'>
): Promise<Subcontract> {
  const res = await api.post<Subcontract>(`/api/pm/projects/${projectId}/subcontracts`, data)
  return res
}

/** 하도급 업체 수정 (개별) */
export async function updateSubcontract(
  subId: number,
  data: Partial<Subcontract>
): Promise<Subcontract> {
  const res = await api.put<Subcontract>(`/api/pm/subcontracts/${subId}`, data)
  return res
}

/** 하도급 업체 삭제 */
export async function deleteSubcontract(subId: number): Promise<void> {
  await api.delete(`/api/pm/subcontracts/${subId}`)
}
