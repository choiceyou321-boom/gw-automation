/**
 * Smart Import AI 패널 — 챗 UI
 * - 메시지 기반 상호작용
 * - 사용자 입력 → AI 분석 → 질문 → 미리보기 → 적용
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { X, Send, Paperclip } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api-client'

interface AnalysisResult {
  analysis_id: string
  detected_type: string
  confidence: number
  extracted_fields: Record<string, any>
  missing_fields: Array<{ field: string; label: string; required: boolean }>
  preview: { type_label: string; items: Array<{ key: string; value: string }> }
}

interface ApplyResponse {
  success: boolean
  message: string
  created_ids: Record<string, number[]>
}

interface Message {
  id: string
  type: 'user' | 'ai' | 'question' | 'preview'
  content: string
  metadata?: Record<string, any>
}

interface SmartImportPanelProps {
  onClose: () => void
}

export function SmartImportPanel({ onClose }: SmartImportPanelProps) {
  const location = useLocation()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [messages, setMessages] = useState<Message[]>([])
  const [inputText, setInputText] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [userAnswers, setUserAnswers] = useState<Record<string, string | undefined>>({})
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)

  // URL에서 projectId 추출
  const projectId = location.pathname.includes('/projects/')
    ? parseInt(location.pathname.split('/')[2])
    : undefined

  // 스크롤 자동
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 초기 인사말
  useEffect(() => {
    setMessages([{
      id: '0',
      type: 'ai',
      content: '📥 Smart Import AI가 준비되었습니다. 텍스트를 붙여넣거나 파일을 업로드하면 자동으로 분석해 프로젝트 데이터에 추가해드립니다.'
    }])
  }, [])

  const handleSubmit = async () => {
    if (!inputText.trim() && !selectedFile) {
      toast.error('텍스트 또는 파일을 입력해주세요')
      return
    }

    // 사용자 메시지 추가
    const userMsg: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: inputText || `📎 ${selectedFile?.name}`
    }
    setMessages(prev => [...prev, userMsg])

    setIsLoading(true)
    try {
      // 파일이 있으면 base64로 인코딩
      let fileB64: string | undefined
      let fileName: string | undefined

      if (selectedFile) {
        const reader = new FileReader()
        fileB64 = await new Promise((resolve) => {
          reader.onload = () => {
            const result = reader.result as string
            resolve(result.split(',')[1])
          }
          reader.readAsDataURL(selectedFile)
        })
        fileName = selectedFile.name
      }

      // API 호출
      const result = await api.post<AnalysisResult>('/api/pm/smart-import/analyze', {
        text: inputText,
        file_b64: fileB64,
        file_name: fileName,
        project_id: projectId
      })

      // 분석 결과 저장
      setAnalysisId(result.analysis_id)
      setAnalysis(result)
      setCurrentQuestionIndex(0)

      // AI 분석 결과 메시지
      const typeLabels: Record<string, string> = {
        estimate: '📋 견적서',
        meeting: '📝 회의록',
        schedule: '📅 일정',
        milestone: '🎯 마일스톤',
        contacts: '👥 연락처',
        collection: '💰 수금',
        overview: '📊 프로젝트 개요',
        unknown: '❓ 미분류'
      }

      const aiMsg: Message = {
        id: Date.now().toString(),
        type: 'ai',
        content: `${typeLabels[result.detected_type] || '분석'} 타입으로 분류되었습니다 (신뢰도: ${(result.confidence * 100).toFixed(0)}%)`,
        metadata: { type: result.detected_type }
      }
      setMessages(prev => [...prev, aiMsg])

      // 빠진 필드가 있으면 질문
      if (result.missing_fields && result.missing_fields.length > 0) {
        const question = result.missing_fields[0]
        const qMsg: Message = {
          id: (Date.now() + 1).toString(),
          type: 'question',
          content: question.label,
          metadata: { field: question.field, required: question.required }
        }
        setMessages(prev => [...prev, qMsg])
      } else {
        // 빠진 필드가 없으면 미리보기
        showPreview(result)
      }

    } catch (error: any) {
      toast.error(`분석 실패: ${error.message}`)
      const errMsg: Message = {
        id: Date.now().toString(),
        type: 'ai',
        content: `❌ 분석 실패: ${error.message}`
      }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setIsLoading(false)
      setInputText('')
      setSelectedFile(null)
    }
  }

  const handleAnswerQuestion = (answer: string) => {
    if (!analysis) return

    // 사용자 답변 저장
    const currentField = analysis.missing_fields[currentQuestionIndex].field
    setUserAnswers(prev => ({ ...prev, [currentField]: answer }))

    // 답변 메시지 추가
    const answerMsg: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: answer
    }
    setMessages(prev => [...prev, answerMsg])

    // 다음 질문 또는 미리보기
    if (currentQuestionIndex + 1 < analysis.missing_fields.length) {
      const nextQuestion = analysis.missing_fields[currentQuestionIndex + 1]
      const nextMsg: Message = {
        id: (Date.now() + 1).toString(),
        type: 'question',
        content: nextQuestion.label,
        metadata: { field: nextQuestion.field, required: nextQuestion.required }
      }
      setMessages(prev => [...prev, nextMsg])
      setCurrentQuestionIndex(currentQuestionIndex + 1)
    } else {
      // 모든 질문 완료 → 미리보기
      showPreview(analysis)
    }
  }

  const showPreview = (analysisResult: AnalysisResult) => {
    const previewMsg: Message = {
      id: Date.now().toString(),
      type: 'preview',
      content: '이 정보가 맞나요? 아래 버튼으로 적용하거나 취소할 수 있습니다.',
      metadata: {
        preview: analysisResult.preview,
        extracted: analysisResult.extracted_fields
      }
    }
    setMessages(prev => [...prev, previewMsg])
  }

  const handleApply = async () => {
    if (!analysisId || !analysis || !projectId) {
      toast.error('적용할 수 없습니다')
      return
    }

    setIsLoading(true)
    try {
      const applyResult = await api.post<ApplyResponse>('/api/pm/smart-import/apply', {
        analysis_id: analysisId,
        user_answers: userAnswers,
        project_id: projectId
      })

      if (applyResult.success) {
        toast.success(applyResult.message)
        const successMsg: Message = {
          id: Date.now().toString(),
          type: 'ai',
          content: `✅ ${applyResult.message}`
        }
        setMessages(prev => [...prev, successMsg])

        // 1500ms 후 패널 종료
        setTimeout(() => {
          onClose()
        }, 1500)
      } else {
        toast.error(applyResult.message)
      }

    } catch (error: any) {
      toast.error(`적용 실패: ${error.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleCancel = async () => {
    if (analysisId) {
      try {
        await api.post('/api/pm/smart-import/cancel', { analysis_id: analysisId })
      } catch (error) {
        logger.error('Cancel failed:', error)
      }
    }
    // 초기 상태로 리셋
    setMessages([{
      id: '0',
      type: 'ai',
      content: '📥 Smart Import AI가 준비되었습니다. 텍스트를 붙여넣거나 파일을 업로드하면 자동으로 분석해 프로젝트 데이터에 추가해드립니다.'
    }])
    setInputText('')
    setSelectedFile(null)
    setAnalysisId(null)
    setAnalysis(null)
    setUserAnswers({})
    setCurrentQuestionIndex(0)
  }

  return (
    <Card className="fixed bottom-24 right-6 w-[420px] h-[640px] z-50 rounded-2xl shadow-xl border border-stone-200 flex flex-col">
      {/* 헤더 */}
      <div className="flex items-center justify-between p-4 border-b border-stone-100">
        <h2 className="text-lg font-semibold text-zinc-900">📥 Smart Import AI</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          className="h-8 w-8 p-0"
        >
          <X size={18} />
        </Button>
      </div>

      {/* 메시지 영역 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isLoading && (
          <div className="flex gap-2">
            <Skeleton className="h-8 w-8 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 질문 입력 영역 (질문 상태일 때) */}
      {analysis && messages[messages.length - 1]?.type === 'question' && (
        <div className="px-4 py-3 border-t border-stone-100">
          <QuestionInput
            question={messages[messages.length - 1].metadata}
            onAnswer={handleAnswerQuestion}
            isLoading={isLoading}
          />
        </div>
      )}

      {/* 적용/취소 버튼 (미리보기 상태일 때) */}
      {analysis && messages[messages.length - 1]?.type === 'preview' && (
        <div className="px-4 py-3 border-t border-stone-100 flex gap-2">
          <Button
            onClick={handleApply}
            disabled={isLoading}
            className="flex-1 bg-zinc-900 hover:bg-zinc-800"
          >
            {isLoading ? '적용 중...' : '적용'}
          </Button>
          <Button
            onClick={handleCancel}
            variant="outline"
            disabled={isLoading}
            className="flex-1"
          >
            다시 입력
          </Button>
        </div>
      )}

      {/* 입력 영역 (초기 또는 분석 완료 후) */}
      {!analysis && (
        <div className="px-4 py-3 border-t border-stone-100 space-y-3">
          <textarea
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            placeholder="텍스트를 붙여넣으세요... (파일 업로드도 가능)"
            className="w-full h-16 p-3 rounded-md border border-stone-200 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-zinc-900"
            disabled={isLoading}
          />

          <div className="flex gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.csv"
              onChange={e => setSelectedFile(e.target.files?.[0] || null)}
              className="hidden"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              variant="outline"
              size="sm"
              disabled={isLoading}
              className="flex gap-1"
            >
              <Paperclip size={16} />
              파일
            </Button>

            {selectedFile && (
              <Badge variant="secondary" className="flex items-center gap-1">
                {selectedFile.name}
                <button
                  onClick={() => setSelectedFile(null)}
                  className="ml-1 hover:text-red-600"
                >
                  ×
                </button>
              </Badge>
            )}

            <Button
              onClick={handleSubmit}
              disabled={isLoading || (!inputText.trim() && !selectedFile)}
              className="ml-auto bg-zinc-900 hover:bg-zinc-800 flex gap-1"
            >
              <Send size={16} />
              분석
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

interface MessageBubbleProps {
  message: Message
}

function MessageBubble({ message }: MessageBubbleProps) {
  if (message.type === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-xs bg-zinc-900 text-white rounded-lg px-4 py-2 text-sm">
          {message.content}
        </div>
      </div>
    )
  }

  if (message.type === 'question') {
    return (
      <div className="flex">
        <div className="max-w-xs bg-stone-100 text-zinc-900 rounded-lg px-4 py-2 text-sm">
          <div className="font-semibold">
            {message.content}
            {message.metadata?.required && (
              <span className="text-red-600 ml-1">*</span>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (message.type === 'preview') {
    const preview = message.metadata?.preview
    return (
      <div className="flex">
        <Card className="max-w-xs p-3 bg-blue-50 border-blue-200">
          <p className="text-sm font-semibold text-zinc-900 mb-2">
            {preview?.type_label}
          </p>
          {preview?.items && preview.items.length > 0 && (
            <div className="space-y-1 mb-3">
              {preview.items.map((item: any, i: number) => (
                <div key={i} className="text-xs text-stone-600">
                  <span className="font-medium">{item.key}:</span> {item.value}
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-stone-600">{message.content}</p>
        </Card>
      </div>
    )
  }

  // AI 메시지 (기본)
  return (
    <div className="flex">
      <div className="max-w-xs bg-stone-100 text-zinc-900 rounded-lg px-4 py-2 text-sm">
        {message.content}
      </div>
    </div>
  )
}

interface QuestionInputProps {
  question?: Record<string, any>
  onAnswer: (answer: string) => void
  isLoading: boolean
}

function QuestionInput({ onAnswer, isLoading }: QuestionInputProps) {
  const [value, setValue] = useState('')

  const handleSubmit = () => {
    if (value.trim()) {
      onAnswer(value)
      setValue('')
    }
  }

  return (
    <div className="flex gap-2">
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyPress={e => e.key === 'Enter' && handleSubmit()}
        placeholder="답변을 입력하세요..."
        className="flex-1 px-3 py-2 rounded-md border border-stone-200 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        disabled={isLoading}
        autoFocus
      />
      <Button
        onClick={handleSubmit}
        disabled={isLoading || !value.trim()}
        className="bg-zinc-900 hover:bg-zinc-800 px-3"
      >
        <Send size={16} />
      </Button>
    </div>
  )
}

// logger 정의 (디버그용)
const logger = { error: console.error }
