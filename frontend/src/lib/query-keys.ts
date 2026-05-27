/**
 * TanStack Query queryKey 단일 소스.
 * 모든 쿼리는 이 팩토리를 거쳐야 함 (오타·키 불일치 방지).
 * invalidation은 prefix 기반: invalidateQueries({ queryKey: queryKeys.projects.all })
 */

export type ProjectFilters = {
  status?: 'active' | 'completed' | 'lease'
  search?: string
}

export type TodoStatus = 'backlog' | 'in_progress' | 'blocked' | 'done'

export const queryKeys = {
  projects: {
    all: ['projects'] as const,
    list: (filters?: ProjectFilters) =>
      ['projects', 'list', filters ?? {}] as const,
    detail: (id: number) => ['projects', id] as const,
    overview: (id: number) => ['projects', id, 'overview'] as const,
    members: (id: number) => ['projects', id, 'members'] as const,
  },
  milestones: {
    all: ['milestones'] as const,
    byProject: (pid: number) => ['milestones', 'project', pid] as const,
  },
  todos: {
    all: ['todos'] as const,
    byProject: (pid: number) => ['todos', 'project', pid] as const,
    byStatus: (s: TodoStatus) => ['todos', 'status', s] as const,
  },
  notifications: {
    all: ['notifications'] as const,
    unread: ['notifications', 'unread'] as const,
  },
  contracts: { all: ['contracts'] as const },
  collections: { all: ['collections'] as const },
  payments: { all: ['payments'] as const },
  portfolio: {
    summary: ['portfolio', 'summary'] as const,
    groups: ['portfolio', 'groups'] as const,
  },
  insights: {
    all: ['insights'] as const,
    byProject: (pid: number) => ['insights', pid] as const,
  },
  auth: { me: ['auth', 'me'] as const },
} as const
