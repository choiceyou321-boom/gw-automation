import { api } from '@/lib/api-client'

export interface ProjectDetail {
  project: Record<string, unknown> & {
    id: number
    name: string
    project_code?: string
    grade?: string
    category?: string
    status?: string
  }
  trades: Array<Record<string, unknown>>
  subcontracts_summary: {
    count: number
    total_contract: number
    total_paid: number
  }
}

export interface ProjectOverview {
  // 백엔드 project_overview 테이블 필드 (모두 nullable)
  location?: string | null
  usage?: string | null
  scale?: string | null
  area?: number | null
  client?: string | null
  contractor?: string | null
  start_date?: string | null
  end_date?: string | null
  duration_days?: number | null
  members?: Array<{ name: string; role?: string; phone?: string }>
  milestones?: Array<{ title: string; due_date?: string; status?: string }>
  [k: string]: unknown
}

export function fetchProjectDetail(projectId: number): Promise<ProjectDetail> {
  return api.get<ProjectDetail>(`/api/pm/projects/${projectId}`)
}

export function fetchProjectOverview(projectId: number): Promise<ProjectOverview> {
  return api
    .get<{ overview: ProjectOverview | null }>(`/api/pm/projects/${projectId}/overview`)
    .then((r) => r.overview ?? {})
}
