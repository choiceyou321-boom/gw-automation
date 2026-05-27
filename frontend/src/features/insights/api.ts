import { api } from '@/lib/api-client'

/** 단일 인사이트 */
export interface Insight {
  insight_type: string // 'strategy' | 'warning' | 'opportunity' 등
  content: string // markdown 가능
  generated_at: string // ISO 8601
  project_id?: number
}

/** /api/pm/insights 응답 */
export interface InsightsResponse {
  portfolio: Insight[]
  projects: Record<number, { project_name: string; items: Insight[] }>
}

/**
 * 전체 AI 인사이트 조회
 */
export function fetchInsights(): Promise<InsightsResponse> {
  return api.get<InsightsResponse>('/api/pm/insights')
}

/**
 * 새 인사이트 생성 (Claude 호출)
 * 시간이 걸릴 수 있음
 */
export function generateInsights(): Promise<unknown> {
  return api.post('/api/pm/insights/generate', {})
}
