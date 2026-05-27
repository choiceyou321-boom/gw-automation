import { useState } from 'react'
import { Download } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { exportData } from '@/lib/export'
import type { ExportColumn, ExportFormat } from '@/lib/export'
import { toast } from 'sonner'

interface Props<T> {
  rows: T[]
  columns: ExportColumn<T>[]
  filenameBase: string
  title?: string
  disabled?: boolean
}

const FORMATS: { key: ExportFormat; label: string }[] = [
  { key: 'csv', label: 'CSV' },
  { key: 'xlsx', label: 'Excel' },
  { key: 'md', label: 'Markdown' },
]

/**
 * 공용 익스포트 버튼 (드롭다운 — CSV/Excel/MD).
 * 인라인 드롭다운 (Popover 미사용 — shadcn Popover 추가 없이도 사용 가능하게).
 */
export function ExportButton<T>({ rows, columns, filenameBase, title, disabled }: Props<T>) {
  const [open, setOpen] = useState(false)

  async function handle(format: ExportFormat) {
    setOpen(false)
    try {
      await exportData(format, rows, columns, filenameBase, title)
      toast.success(`${rows.length}건 익스포트 완료 (${format.toUpperCase()})`)
    } catch (e) {
      toast.error(`익스포트 실패: ${(e as Error).message}`)
    }
  }

  return (
    <div className="relative">
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || rows.length === 0}
      >
        <Download size={14} />
        익스포트
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-10 z-50 min-w-32 rounded-md border border-stone-200 bg-white shadow-soft-md">
            {FORMATS.map((f) => (
              <button
                key={f.key}
                onClick={() => handle(f.key)}
                className="block w-full px-3 py-2 text-left text-sm hover:bg-stone-50"
              >
                {f.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
