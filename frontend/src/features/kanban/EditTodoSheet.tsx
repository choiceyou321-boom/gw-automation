import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { updateTodo, deleteTodo } from './api'
import type { KanbanTodo } from './api'

interface EditTodoSheetProps {
  todo: KanbanTodo | null
  isOpen: boolean
  onOpenChange: (open: boolean) => void
}

const PRIORITY_OPTIONS = ['low', 'medium', 'high']
const CATEGORY_OPTIONS = ['', 'feature', 'bug', 'docs', 'refactor', 'blocked']

export function EditTodoSheet({ todo, isOpen, onOpenChange }: EditTodoSheetProps) {
  const qc = useQueryClient()

  const [content, setContent] = useState(todo?.content ?? '')
  const [priority, setPriority] = useState(todo?.priority ?? 'medium')
  const [category, setCategory] = useState(todo?.category ?? '')

  // 항상 최신 todo로 업데이트
  const current = isOpen ? todo : null

  const updateMutation = useMutation({
    mutationFn: () =>
      updateTodo(current!.id, {
        content: content !== current?.content ? content : undefined,
        priority: priority !== current?.priority ? priority : undefined,
        category: category !== current?.category ? category : undefined,
      }),
    onSuccess: () => {
      toast.success('저장되었습니다')
      onOpenChange(false)
      qc.invalidateQueries({ queryKey: ['kanban'] })
    },
    onError: (error) => {
      toast.error(`저장 실패: ${(error as Error).message}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteTodo(current!.id),
    onSuccess: () => {
      toast.success('삭제되었습니다')
      onOpenChange(false)
      qc.invalidateQueries({ queryKey: ['kanban'] })
    },
    onError: (error) => {
      toast.error(`삭제 실패: ${(error as Error).message}`)
    },
  })

  const handleDelete = () => {
    if (window.confirm('정말 삭제하시겠습니까?')) {
      deleteMutation.mutate()
    }
  }

  const handleOpenChange = (open: boolean) => {
    if (open) return
    // 닫을 때만 처리
    onOpenChange(false)
  }

  const isDirty =
    content !== current?.content || priority !== current?.priority || category !== current?.category

  if (!current) return null

  return (
    <Sheet open={isOpen} onOpenChange={handleOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>할일 편집</SheetTitle>
          <SheetDescription>
            내용, 우선도, 카테고리를 변경할 수 있습니다.
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 py-4">
          {/* 프로젝트 */}
          {current.project_name && (
            <div className="space-y-2">
              <label className="text-sm font-medium">프로젝트</label>
              <Badge variant="secondary">{current.project_name}</Badge>
            </div>
          )}

          {/* 내용 */}
          <div className="space-y-2">
            <label htmlFor="content" className="text-sm font-medium">
              내용
            </label>
            <textarea
              id="content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="할일 내용"
              rows={3}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder-muted-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {/* 우선도 */}
          <div className="space-y-2">
            <label htmlFor="priority" className="text-sm font-medium">
              우선도
            </label>
            <select
              id="priority"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {PRIORITY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === 'low' ? '낮음' : opt === 'medium' ? '중간' : '높음'}
                </option>
              ))}
            </select>
          </div>

          {/* 카테고리 */}
          <div className="space-y-2">
            <label htmlFor="category" className="text-sm font-medium">
              카테고리
            </label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {CATEGORY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {!opt ? '없음' : opt}
                </option>
              ))}
            </select>
          </div>
        </div>

        <SheetFooter className="flex-row justify-between pt-4">
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
          >
            삭제
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              취소
            </Button>
            <Button
              onClick={() => updateMutation.mutate()}
              disabled={!isDirty || updateMutation.isPending}
            >
              저장
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
