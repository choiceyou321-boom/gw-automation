/**
 * Smart Import AI FAB (Floating Action Button)
 * - 우하단 고정 위치
 * - 클릭 시 패널 펼침
 */
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Sparkles } from 'lucide-react'
import { SmartImportPanel } from '@/features/smart-import/SmartImportPanel'

export function SmartImportFAB() {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      {/* FAB 버튼 */}
      {!isOpen && (
        <Button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-zinc-900 text-white shadow-md hover:scale-105 transition-transform duration-200 flex items-center justify-center p-0"
        >
          <Sparkles size={22} />
        </Button>
      )}

      {/* 패널 */}
      {isOpen && (
        <SmartImportPanel onClose={() => setIsOpen(false)} />
      )}
    </>
  )
}
