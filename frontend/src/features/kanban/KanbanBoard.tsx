import { useState } from 'react'
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  closestCenter,
} from '@dnd-kit/core'
import type { DragEndEvent, DragStartEvent, UniqueIdentifier } from '@dnd-kit/core'
import { useDroppable, useDraggable } from '@dnd-kit/core'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { fetchKanban, updateTodo, todoFieldsForStatus } from './api'
import type { KanbanBoard, KanbanStatus, KanbanTodo } from './api'

// v6: 모든 컬럼 무채색 stone-50 → 컬럼 카운트 배지로만 시각 구분
const COLUMNS: { key: KanbanStatus; label: string; cls: string }[] = [
  { key: 'backlog', label: '백로그', cls: 'bg-stone-50' },
  { key: 'in_progress', label: '진행', cls: 'bg-stone-50' },
  { key: 'blocked', label: '차단', cls: 'bg-stone-50' },
  { key: 'done', label: '완료', cls: 'bg-stone-50' },
]

interface Props {
  projectId?: number
}

export function KanbanBoardView({ projectId }: Props) {
  const qc = useQueryClient()
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  const board = useQuery({
    queryKey: projectId ? ['kanban', 'project', projectId] : ['kanban', 'all'],
    queryFn: () => fetchKanban(projectId),
  })

  const [activeId, setActiveId] = useState<UniqueIdentifier | null>(null)
  const [optimistic, setOptimistic] = useState<KanbanBoard | null>(null)

  const current = optimistic ?? board.data ?? null

  const mutation = useMutation({
    mutationFn: ({ todoId, status }: { todoId: number; status: KanbanStatus }) =>
      updateTodo(todoId, todoFieldsForStatus(status)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['kanban'] })
      setOptimistic(null)
    },
  })

  function findTodo(id: number): { todo: KanbanTodo; from: KanbanStatus } | null {
    if (!current) return null
    for (const col of COLUMNS) {
      const found = current[col.key].find((t) => t.id === id)
      if (found) return { todo: found, from: col.key }
    }
    return null
  }

  function moveOptimistic(todoId: number, target: KanbanStatus) {
    if (!current) return
    const found = findTodo(todoId)
    if (!found || found.from === target) return
    const next: KanbanBoard = {
      backlog: [...current.backlog],
      in_progress: [...current.in_progress],
      blocked: [...current.blocked],
      done: [...current.done],
    }
    next[found.from] = next[found.from].filter((t) => t.id !== todoId)
    next[target] = [{ ...found.todo, status: target }, ...next[target]]
    setOptimistic(next)
  }

  function handleDragEnd(e: DragEndEvent) {
    setActiveId(null)
    const todoId = Number(e.active.id)
    const overId = e.over?.id?.toString()
    if (!overId || !todoId) return
    const target = overId as KanbanStatus
    if (!COLUMNS.find((c) => c.key === target)) return
    moveOptimistic(todoId, target)
    mutation.mutate({ todoId, status: target })
  }

  function handleDragStart(e: DragStartEvent) {
    setActiveId(e.active.id)
  }

  if (board.isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {COLUMNS.map((c) => (
          <Skeleton key={c.key} className="h-64" />
        ))}
      </div>
    )
  }

  if (board.isError) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
        칸반 로드 실패: {(board.error as Error).message}
      </div>
    )
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {COLUMNS.map((col) => (
          <Column
            key={col.key}
            statusKey={col.key}
            label={col.label}
            cls={col.cls}
            todos={current?.[col.key] ?? []}
            activeId={activeId}
          />
        ))}
      </div>
    </DndContext>
  )
}

function Column({
  statusKey,
  label,
  cls,
  todos,
  activeId,
}: {
  statusKey: KanbanStatus
  label: string
  cls: string
  todos: KanbanTodo[]
  activeId: UniqueIdentifier | null
}) {
  const { setNodeRef, isOver } = useDroppable({ id: statusKey })
  return (
    <Card
      ref={setNodeRef as any}
      className={cn('flex flex-col', cls, isOver && 'ring-2 ring-ring')}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">{label}</CardTitle>
          <Badge variant="outline">{todos.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-2 overflow-y-auto pb-3">
        {todos.length === 0 ? (
          <p className="py-6 text-center text-xs text-muted-foreground">비어 있음</p>
        ) : (
          todos.map((t) => (
            <TodoCard key={t.id} todo={t} dragging={String(t.id) === String(activeId)} />
          ))
        )}
      </CardContent>
    </Card>
  )
}

function TodoCard({ todo, dragging }: { todo: KanbanTodo; dragging: boolean }) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: todo.id })
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={cn(
        'cursor-grab rounded-md border bg-card p-3 shadow-sm transition-shadow hover:shadow-md',
        dragging && 'opacity-50',
      )}
    >
      <p className="text-sm leading-snug">{todo.content}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1 text-[10px]">
        {todo.project_name && (
          <Badge variant="outline" className="px-1.5 py-0">
            {todo.project_name}
          </Badge>
        )}
        {todo.priority && todo.priority !== 'medium' && (
          <Badge
            variant={todo.priority === 'high' ? 'warning' : 'secondary'}
            className="px-1.5 py-0"
          >
            {todo.priority}
          </Badge>
        )}
        {todo.category && (
          <Badge variant="secondary" className="px-1.5 py-0">
            {todo.category}
          </Badge>
        )}
      </div>
    </div>
  )
}

