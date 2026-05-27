import { api } from '@/lib/api-client'

export type KanbanStatus = 'backlog' | 'in_progress' | 'blocked' | 'done'

export interface KanbanTodo {
  id: number
  project_id: number | null
  project_name?: string
  content: string
  completed: number
  priority: string
  category: string
  // 백엔드 응답이 status 키를 갖는지 컬럼 안에 들어가는지에 따라
  status?: KanbanStatus
  [k: string]: unknown
}

export interface KanbanBoard {
  backlog: KanbanTodo[]
  in_progress: KanbanTodo[]
  blocked: KanbanTodo[]
  done: KanbanTodo[]
}

export function fetchKanban(projectId?: number): Promise<KanbanBoard> {
  return api.get<KanbanBoard>('/api/pm/kanban', {
    searchParams: projectId ? { project_id: projectId } : undefined,
  })
}

/** 상태별 todo 필드 매핑 (backend의 분류 규칙과 정합) */
export function todoFieldsForStatus(status: KanbanStatus): {
  completed: number
  priority?: string
  category?: string
} {
  switch (status) {
    case 'done':
      return { completed: 1 }
    case 'in_progress':
      return { completed: 0, priority: 'high', category: '' }
    case 'blocked':
      return { completed: 0, priority: 'medium', category: 'blocked' }
    case 'backlog':
    default:
      return { completed: 0, priority: 'medium', category: '' }
  }
}

export function updateTodo(
  todoId: number,
  patch: { content?: string; completed?: number; priority?: string; category?: string; project_id?: number },
): Promise<unknown> {
  return api.put(`/api/pm/todos/${todoId}`, patch)
}
