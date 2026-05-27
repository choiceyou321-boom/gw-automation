import { api } from '@/lib/api-client'

export interface ScheduleItem {
  id: number
  project_id: number
  item_name: string
  start_date: string
  end_date: string
  status: string // 'planned' | 'in_progress' | 'done' | 'blocked' | 'critical'
  color?: string | null
  notes?: string | null
  sort_order?: number
}

export function fetchProjectSchedule(projectId: number): Promise<ScheduleItem[]> {
  return api
    .get<{ items: ScheduleItem[] }>(`/api/pm/projects/${projectId}/schedule`)
    .then((r) => r.items)
}
