import { api } from '@/lib/api-client'

/** 알림 항목 인터페이스 */
export interface NotificationItem {
  id: number
  project_id: number | null
  project_name?: string
  notification_type: string
  message: string
  read: number
  created_at: string
}

/** 주간 다이제스트 응답 인터페이스 */
export interface DigestMilestone {
  id: number
  project_name: string
  title: string
  due_date: string
  days_left: number
}

export interface DigestPayment {
  id: number
  project_name: string
  amount: number
  date: string
}

export interface DigestContract {
  id: number
  project_name: string
  title: string
  date: string
}

export interface WeeklyDigest {
  generated_at: string
  unread_notifications: number
  upcoming_milestones: DigestMilestone[]
  overdue_milestones: DigestMilestone[]
  recent_payments: DigestPayment[]
  new_contracts: DigestContract[]
}

/** 알림 목록 조회 */
export function fetchNotifications(): Promise<NotificationItem[]> {
  return api
    .get<{ notifications: NotificationItem[] }>('/api/pm/notifications')
    .then((r) => r.notifications)
}

/** 모든 알림 읽음 처리 */
export function markAllNotificationsRead(): Promise<void> {
  return api.post('/api/pm/notifications/read-all')
}

/** 주간 다이제스트 조회 */
export function fetchWeeklyDigest(): Promise<WeeklyDigest> {
  return api.get<WeeklyDigest>('/api/pm/digest/weekly')
}
