import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { createTodo } from './api'
import type { KanbanStatus } from './api'

interface AddTodoFormProps {
  status: KanbanStatus
  projectId?: number
}

export function AddTodoForm({ status, projectId }: AddTodoFormProps) {
  const qc = useQueryClient()
  const [isOpen, setIsOpen] = useState(false)
  const [content, setContent] = useState('')

  // 상태별로 카테고리 설정 (status → category 매핑)
  const getDefaultCategory = () => {
    switch (status) {
      case 'blocked':
        return 'blocked'
      default:
        return ''
    }
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createTodo({
        project_id: projectId,
        content,
        category: getDefaultCategory(),
      }),
    onSuccess: () => {
      toast.success('할일이 추가되었습니다')
      setContent('')
      setIsOpen(false)
      qc.invalidateQueries({ queryKey: ['kanban'] })
    },
    onError: (error) => {
      toast.error(`추가 실패: ${(error as Error).message}`)
    },
  })

  if (!isOpen) {
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setIsOpen(true)}
        className="w-full justify-start text-muted-foreground hover:text-foreground"
      >
        <Plus className="h-4 w-4" />
        <span>추가</span>
      </Button>
    )
  }

  return (
    <div className="space-y-2">
      <input
        autoFocus
        type="text"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            createMutation.mutate()
          } else if (e.key === 'Escape') {
            setIsOpen(false)
            setContent('')
          }
        }}
        placeholder="새로운 할일 입력..."
        className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder-muted-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="flex gap-1">
        <Button
          size="sm"
          variant="default"
          onClick={() => createMutation.mutate()}
          disabled={!content || createMutation.isPending}
        >
          저장
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setIsOpen(false)
            setContent('')
          }}
          disabled={createMutation.isPending}
        >
          취소
        </Button>
      </div>
    </div>
  )
}
