import { useState, useEffect } from 'react'
import { Trash2 } from 'lucide-react'

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { createSubcontract, updateSubcontract, deleteSubcontract, type Subcontract } from '@/features/vendors/api'
import type { PortfolioRow } from '@/features/projects/api'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId?: number
  projects: PortfolioRow[]
  subcontract?: Subcontract
  onSaveSuccess: () => void
  onDeleteSuccess: () => void
}

export function SubcontractSheet({
  open,
  onOpenChange,
  projectId,
  projects,
  subcontract,
  onSaveSuccess,
  onDeleteSuccess,
}: Props) {
  const [isSaving, setIsSaving] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [formData, setFormData] = useState<Partial<Subcontract>>({})

  // 폼 초기화
  useEffect(() => {
    if (subcontract) {
      setFormData(subcontract)
    } else {
      setFormData({
        project_id: projectId,
        company_name: '',
        contract_amount: 0,
        remaining_amount: 0,
      })
    }
  }, [open, subcontract, projectId])

  const handleChange = (field: keyof Subcontract, value: unknown) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  const handleSave = async () => {
    // 유효성 검사
    if (!formData.project_id) {
      toast.error('프로젝트를 선택해주세요.')
      return
    }
    if (!formData.company_name?.trim()) {
      toast.error('업체명을 입력해주세요.')
      return
    }

    setIsSaving(true)
    try {
      if (subcontract?.id) {
        // 수정
        const { id, created_at, updated_at, ...data } = formData as any
        await updateSubcontract(subcontract.id, data)
      } else {
        // 추가
        const { id, created_at, updated_at, ...data } = formData as any
        await createSubcontract(formData.project_id, data)
      }
      onSaveSuccess()
    } catch (error) {
      toast.error(`저장 실패: ${(error as Error).message}`)
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!subcontract?.id) return
    if (!confirm('정말 삭제하시겠습니까?')) return

    setIsDeleting(true)
    try {
      await deleteSubcontract(subcontract.id)
      onDeleteSuccess()
    } catch (error) {
      toast.error(`삭제 실패: ${(error as Error).message}`)
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{subcontract ? '하도급 편집' : '하도급 추가'}</SheetTitle>
        </SheetHeader>

        <div className="space-y-4 py-6">
          {/* 프로젝트 선택 */}
          <div>
            <label className="text-sm font-medium">프로젝트 *</label>
            <select
              value={String(formData.project_id || '')}
              onChange={(e) => handleChange('project_id', Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              disabled={!!subcontract}
            >
              <option value="">선택해주세요</option>
              {projects.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {/* 업체명 */}
          <div>
            <label className="text-sm font-medium">업체명 *</label>
            <input
              type="text"
              value={formData.company_name || ''}
              onChange={(e) => handleChange('company_name', e.target.value)}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              placeholder="업체명을 입력해주세요"
            />
          </div>

          {/* 계약금액 */}
          <div>
            <label className="text-sm font-medium">계약금액</label>
            <input
              type="number"
              value={formData.contract_amount || 0}
              onChange={(e) => handleChange('contract_amount', Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>

          {/* 잔액 */}
          <div>
            <label className="text-sm font-medium">잔액</label>
            <input
              type="number"
              value={formData.remaining_amount || 0}
              onChange={(e) => handleChange('remaining_amount', Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>

          {/* 1~4차 기성 */}
          {[1, 2, 3, 4].map((i) => {
            const paymentKey = `payment_${i}` as keyof Subcontract
            const value = formData[paymentKey]
            return (
              <div key={i}>
                <label className="text-sm font-medium">{i}차 기성</label>
                <input
                  type="number"
                  value={typeof value === 'number' ? value : 0}
                  onChange={(e) => handleChange(paymentKey, Number(e.target.value))}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                />
              </div>
            )
          })}
        </div>

        <SheetFooter className="gap-2">
          {subcontract && (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              disabled={isDeleting || isSaving}
              className="mr-auto"
            >
              <Trash2 size={14} />
              삭제
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button size="sm" onClick={handleSave} disabled={isSaving}>
            {isSaving ? '저장 중...' : '저장'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
