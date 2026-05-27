import { api } from '@/lib/api-client'

export interface Subcontract {
  id: number
  project_id: number
  trade_name?: string
  vendor_name?: string
  contract_amount?: number
  payment_1?: number
  payment_2?: number
  payment_3?: number
  payment_4?: number
  payment_1_confirmed?: number
  payment_2_confirmed?: number
  payment_3_confirmed?: number
  payment_4_confirmed?: number
  [k: string]: unknown
}

export interface Collection {
  id: number
  project_id: number
  amount?: number
  collected?: number
  scheduled_date?: string
  description?: string
  [k: string]: unknown
}

export interface Payment {
  id: number
  project_id: number
  accounting_unit?: string
  scheduled_date?: string
  payment_date?: string
  amount?: number
  vendor?: string
  memo?: string
  [k: string]: unknown
}

export function fetchSubcontracts(projectId: number): Promise<Subcontract[]> {
  return api
    .get<{ subcontracts: Subcontract[] }>(`/api/pm/projects/${projectId}/subcontracts`)
    .then((r) => r.subcontracts)
}

export function fetchCollections(projectId: number): Promise<Collection[]> {
  return api
    .get<{ collections: Collection[] }>(`/api/pm/projects/${projectId}/collections`)
    .then((r) => r.collections)
}

export function fetchPayments(projectId: number, limit = 200): Promise<Payment[]> {
  return api
    .get<{ payments: Payment[] }>(`/api/pm/projects/${projectId}/payments`, {
      searchParams: { limit },
    })
    .then((r) => r.payments)
}
