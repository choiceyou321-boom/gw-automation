import { useEffect, useState } from 'react'
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

interface EditScheduleItemSheetProps {
  projectId: number | null
  item: ScheduleItem | null
  allItems: ScheduleItem[]
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  onSuccess?: () => void
}

const STATUS_OPTIONS = ['planned', 'in_progress', 'done', 'blocked', 'critical']

export function EditScheduleItemSheet({
  projectId,
  item,
  allItems,
  isOpen,
  onOpenChange,
  onSuccess,
}: EditScheduleItemSheetProps) {
  const qc = useQueryClient()
  const [itemName, setItemName] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [status, setStatus] = useState('planned')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (item) {
      setItemName(item.item_name)
      setStartDate(item.start_date)
      setEndDate(item.end_date)
      setStatus(item.status)
      setNotes(item.notes ?? '')
    }
  }, [item, isOpen])

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!projectId || !item) throw new Error('항목 정보가 없습니다')
      if (!itemName) throw new Error('항목명을 입력하세요')
      if (!startDate) throw new Error('시작일을 입력하세요')
      if (!endDate) throw new Error('종료일을 입력하세요')

      const updatedItems = allItems.map((it) =>
        it.id === item.id
          ? {
              ...it,
              item_name: itemName,
              start_date: startDate,
              end_date: endDate,
              status,
              notes: notes || undefined,
            }
          : it,
      )

      return updateProjectSchedule(projectId, updatedItems)
    },
    onSuccess: () => {
      toast.success('저장되었습니다')
      onOpenChange(false)
      qc.invalidateQueries({ queryKey: ['schedule'] })
      onSuccess?.()
    },
    onError: (error) => {
      toast.error(`저장 실패: ${(error as Error).message}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!projectId || !item) throw new Error('항목 정보가 없습니다')

      const updatedItems = allItems.filter((it) => it.id !== item.id)
      return updateProjectSchedule(projectId, updatedItems)
    },
    onSuccess: () => {
      toast.success('삭제되었습니다')
      onOpenChange(false)
      qc.invalidateQueries({ queryKey: ['schedule'] })
      onSuccess?.()
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

  const isDirty =
    itemName !== item?.item_name ||
    startDate !== item?.start_date ||
    endDate !== item?.end_date ||
    status !== item?.status ||
    notes !== (item?.notes ?? '')

  if (!item) return null

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>일정 항목 편집</SheetTitle>
          <SheetDescription>항목 정보를 변경할 수 있습니다.</SheetDescription>
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

        <SheetFooter className="flex-row justify-between pt-4">
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
          >
            삭제
          </Button>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saveMutation.isPending || deleteMutation.isPending}
            >
              취소
            </Button>
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={
                !itemName ||
                !startDate ||
                !endDate ||
                !isDirty ||
                saveMutation.isPending ||
                deleteMutation.isPending
              }
            >
              저장
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
