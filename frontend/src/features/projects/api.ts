import { api } from '@/lib/api-client'

/** /api/pm/portfolio-summary 응답 1건 (백엔드 get_portfolio_summary 참조) */
export interface PortfolioRow {
  id: number
  name: string
  grade: string
  category: string
  total_order: number
  execution_budget: number
  profit_amount: number
  profit_rate: number
  coll_total: number
  coll_collected: number
  coll_rate: number
  payment_limit: number
  total_paid: number
  // 백엔드가 더 많은 필드를 반환할 수 있음 (openapi 타입 자동 생성 시 정합)
  [k: string]: unknown
}

export function fetchPortfolioSummary(): Promise<PortfolioRow[]> {
  return api
    .get<{ projects: PortfolioRow[] }>('/api/pm/portfolio-summary')
    .then((r) => r.projects)
}

export interface NotificationItem {
  id: number
  project_id: number | null
  project_name?: string
  notification_type: string
  message: string
  read: number
  created_at: string
}

export function fetchNotifications(): Promise<NotificationItem[]> {
  return api
    .get<{ notifications: NotificationItem[] }>('/api/pm/notifications')
    .then((r) => r.notifications)
}
