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
import { updateProjectSchedule } from './api'
import type { ScheduleItem } from './api'

interface AddScheduleItemSheetProps {
  projectId: number | null
  existingItems: ScheduleItem[]
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSuccess?: () => void
}

const STATUS_OPTIONS = ['planned', 'in_progress', 'done', 'blocked', 'critical']

export function AddScheduleItemSheet({
  projectId,
  existingItems,
  isOpen,
  onOpenChange,
  onSuccess,
}: AddScheduleItemSheetProps) {
  const qc = useQueryClient()
  const [itemName, setItemName] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [status, setStatus] = useState('planned')
  const [notes, setNotes] = useState('')

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('프로젝트를 선택하세요')
      if (!itemName) throw new Error('항목명을 입력하세요')
      if (!startDate) throw new Error('시작일을 입력하세요')
      if (!endDate) throw new Error('종료일을 입력하세요')

      // 새 항목 생성 (id는 서버에서 할당)
      const newItem: ScheduleItem = {
        id: Date.now(), // 임시 id (서버에서 바뀔 것)
        project_id: projectId,
        item_name: itemName,
        start_date: startDate,
        end_date: endDate,
        status,
        notes: notes || undefined,
      }

      const updatedItems = [...existingItems, newItem]
      return updateProjectSchedule(projectId, updatedItems)
    },
    onSuccess: () => {
      toast.success('일정 항목이 추가되었습니다')
      setItemName('')
      setStartDate('')
      setEndDate('')
      setStatus('planned')
      setNotes('')
      onOpenChange(false)
      qc.invalidateQueries({ queryKey: ['schedule'] })
      onSuccess?.()
    },
    onError: (error) => {
      toast.error(`추가 실패: ${(error as Error).message}`)
    },
  })

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>일정 항목 추가</SheetTitle>
          <SheetDescription>새 공정 항목을 추가합니다.</SheetDescription>
        </SheetHeader>

        <div className="space-y-4 py-4">
          {/* 항목명 */}
          <div className="space-y-2">
            <label htmlFor="itemName" className="text-sm font-medium">
              항목명 *
            </label>
            <input
              id="itemName"
              value={itemName}
              onChange={(e) => setItemName(e.target.value)}
              placeholder="예: 기초공사"
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {/* 시작일 */}
          <div className="space-y-2">
            <label htmlFor="startDate" className="text-sm font-medium">
              시작일 *
            </label>
            <input
              id="startDate"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {/* 종료일 */}
          <div className="space-y-2">
            <label htmlFor="endDate" className="text-sm font-medium">
              종료일 *
            </label>
            <input
              id="endDate"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {/* 상태 */}
          <div className="space-y-2">
            <label htmlFor="status" className="text-sm font-medium">
              상태 *
            </label>
            <select
              id="status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === 'planned'
                    ? '계획'
                    : opt === 'in_progress'
                      ? '진행'
                      : opt === 'done'
                        ? '완료'
                        : opt === 'blocked'
                          ? '차단'
                          : 'CP'}
                </option>
              ))}
            </select>
          </div>

          {/* 비고 */}
          <div className="space-y-2">
            <label htmlFor="notes" className="text-sm font-medium">
              비고
            </label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="추가 설명"
              rows={2}
              className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        </div>

        <SheetFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saveMutation.isPending}
          >
            취소
          </Button>
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={!itemName || !startDate || !endDate || saveMutation.isPending}
          >
            추가
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
