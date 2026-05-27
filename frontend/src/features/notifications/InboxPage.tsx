import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Bell, Check } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ExportButton } from '@/components/ExportButton'
import type { ExportColumn } from '@/lib/export'
import { fetchNotifications, markAllNotificationsRead } from './api'
import { DigestPanel } from './DigestPanel'
import { queryKeys } from '@/lib/query-keys'
import type { NotificationItem } from './api'
import { formatDate } from '@/lib/format'

const NOTIFICATION_TYPE_LABELS: Record<string, string> = {
  milestone: '마일스톤',
  payment: '결제',
  contract: '계약',
  approval: '승인',
  alert: '알림',
}

const NOTIFICATION_TYPE_COLORS: Record<string, string> = {
  milestone: 'bg-blue-100 text-blue-800',
  payment: 'bg-green-100 text-green-800',
  contract: 'bg-purple-100 text-purple-800',
  approval: 'bg-orange-100 text-orange-800',
  alert: 'bg-red-100 text-red-800',
}

type FilterTab = 'all' | 'unread'

/**
 * 인박스 페이지 — 1556건 알림 + 필터 + 검색 + 페이지네이션
 * 좌측: 알림 리스트
 * 우측: 주간 다이제스트 패널
 */
export function InboxPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [filterTab, setFilterTab] = useState<FilterTab>('all')
  const [search, setSearch] = useState('')
  const [selectedProject, setSelectedProject] = useState<number | null>(null)
  const [showDigest, setShowDigest] = useState(true)
  const [displayCount, setDisplayCount] = useState(50)

  // 알림 조회
  const {
    data: allNotifications = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: queryKeys.notifications.all,
    queryFn: fetchNotifications,
    staleTime: 10 * 1000,
  })

  // 모두 읽음 처리
  const markAllMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.notifications.all,
      })
    },
  })

  // 필터링 로직
  const unreadCount = useMemo(
    () => allNotifications.filter((n) => !n.read).length,
    [allNotifications],
  )

  const projects = useMemo(() => {
    const set = new Set<number>()
    allNotifications.forEach((n) => {
      if (n.project_id) set.add(n.project_id)
    })
    return Array.from(set).sort()
  }, [allNotifications])

  const filtered = useMemo(() => {
    let arr = allNotifications

    // 읽음 상태 필터
    if (filterTab === 'unread') {
      arr = arr.filter((n) => !n.read)
    }

    // 프로젝트 필터
    if (selectedProject !== null) {
      arr = arr.filter((n) => n.project_id === selectedProject)
    }

    // 검색 필터
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      arr = arr.filter((n) =>
        n.message.toLowerCase().includes(q) ||
        (n.project_name?.toLowerCase().includes(q) ?? false),
      )
    }

    // 최신순 정렬
    return arr.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
  }, [allNotifications, filterTab, selectedProject, search])

  // 표시 항목 (페이지네이션)
  const displayedItems = filtered.slice(0, displayCount)
  const hasMore = filtered.length > displayCount

  // 상대시간 포맷
  const formatRelativeTime = (iso: string): string => {
    const now = new Date()
    const then = new Date(iso)
    const diff = now.getTime() - then.getTime()
    const mins = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    const days = Math.floor(diff / 86400000)

    if (mins < 1) return '방금'
    if (mins < 60) return `${mins}분 전`
    if (hours < 24) return `${hours}시간 전`
    if (days < 7) return `${days}일 전`
    return then.toLocaleDateString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
    })
  }

  // 알림 항목 클릭 → 프로젝트 상세 이동
  const handleNotificationClick = (notification: NotificationItem) => {
    if (notification.project_id) {
      navigate({
        to: '/projects/$projectId',
        params: { projectId: String(notification.project_id) },
      })
    }
  }

  // 익스포트 컬럼 정의
  const exportColumns: ExportColumn<NotificationItem>[] = [
    { key: 'notification_type', label: '유형' },
    { key: 'project_name', label: '프로젝트' },
    { key: 'message', label: '메시지' },
    {
      key: 'read',
      label: '읽음 여부',
      format: (row) => (row.read ? '읽음' : '미읽음'),
    },
    {
      key: 'created_at',
      label: '생성일',
      format: (row) => formatDate(row.created_at),
    },
  ]

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">알림</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            총 {allNotifications.length}건 • 읽지 않음 {unreadCount}건
          </p>
        </div>
        <div className="flex gap-2">
          <ExportButton
            rows={allNotifications}
            columns={exportColumns}
            filenameBase="inbox"
            title="알림"
            disabled={isLoading}
          />
          <Button
            variant={showDigest ? 'default' : 'outline'}
            size="sm"
            onClick={() => setShowDigest(!showDigest)}
          >
            다이제스트
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => markAllMutation.mutate()}
            disabled={unreadCount === 0 || markAllMutation.isPending}
            className="gap-1"
          >
            <Check className="h-4 w-4" />
            모두 읽음
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 알림 리스트 — lg에서 2/3 너비 */}
        <div className="lg:col-span-2">
          {/* 필터 탭 */}
          <Tabs value={filterTab} onValueChange={(v) => setFilterTab(v as FilterTab)}>
            <TabsList className="mb-4 grid w-full grid-cols-2">
              <TabsTrigger value="all">
                전체 ({allNotifications.length})
              </TabsTrigger>
              <TabsTrigger value="unread">
                미읽음 ({unreadCount})
              </TabsTrigger>
            </TabsList>

            <div className="space-y-4">
              {/* 검색 */}
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="메시지나 프로젝트명 검색..."
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />

              {/* 프로젝트 필터 */}
              {projects.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant={selectedProject === null ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setSelectedProject(null)}
                  >
                    모든 프로젝트
                  </Button>
                  {projects.map((pid) => {
                    const projectName =
                      allNotifications.find((n) => n.project_id === pid)?.project_name || `#${pid}`
                    return (
                      <Button
                        key={pid}
                        variant={selectedProject === pid ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => setSelectedProject(pid)}
                      >
                        {projectName}
                      </Button>
                    )
                  })}
                </div>
              )}

              {/* 알림 리스트 로드 중 */}
              {isLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-16" />
                  ))}
                </div>
              ) : isError ? (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
                  알림 로드 실패: {(error as Error)?.message ?? 'Unknown error'}
                </div>
              ) : displayedItems.length === 0 ? (
                <Card className="p-8 text-center">
                  <Bell className="mx-auto mb-2 h-12 w-12 text-muted-foreground/40" />
                  <p className="text-sm text-muted-foreground">
                    {search.trim() || selectedProject !== null
                      ? '조건에 맞는 알림이 없습니다.'
                      : '알림이 없습니다.'}
                  </p>
                </Card>
              ) : (
                <>
                  {/* 알림 항목 */}
                  <div className="space-y-2">
                    {displayedItems.map((notification) => (
                      <Card
                        key={notification.id}
                        className={`cursor-pointer border-l-4 p-3 transition-colors hover:bg-muted ${
                          !notification.read
                            ? 'border-l-blue-500 bg-blue-50'
                            : 'border-l-gray-200'
                        }`}
                        onClick={() => handleNotificationClick(notification)}
                      >
                        <div className="flex items-start gap-3">
                          {/* 타입 배지 */}
                          <Badge
                            className={`${NOTIFICATION_TYPE_COLORS[notification.notification_type] || 'bg-gray-100 text-gray-800'}`}
                          >
                            {NOTIFICATION_TYPE_LABELS[notification.notification_type] ||
                              notification.notification_type}
                          </Badge>

                          {/* 콘텐츠 */}
                          <div className="flex-1 min-w-0">
                            <p
                              className={`text-sm ${
                                !notification.read
                                  ? 'font-semibold'
                                  : 'font-normal text-foreground'
                              }`}
                            >
                              {notification.message}
                            </p>
                            <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                              {notification.project_name && (
                                <span className="rounded-full bg-gray-100 px-2 py-0.5">
                                  {notification.project_name}
                                </span>
                              )}
                              <span>{formatRelativeTime(notification.created_at)}</span>
                            </div>
                          </div>

                          {/* 읽음 표시 */}
                          {!notification.read && (
                            <div className="mt-1 h-2 w-2 flex-shrink-0 rounded-full bg-blue-500" />
                          )}
                        </div>
                      </Card>
                    ))}
                  </div>

                  {/* "더 보기" 버튼 */}
                  {hasMore && (
                    <div className="flex justify-center pt-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setDisplayCount((c) => c + 50)}
                      >
                        더 보기 ({filtered.length - displayCount}건 남음)
                      </Button>
                    </div>
                  )}

                  {/* 총 개수 표시 */}
                  <div className="text-center text-xs text-muted-foreground">
                    {displayCount >= filtered.length && filtered.length > 0
                      ? `${filtered.length}건 모두 표시됨`
                      : null}
                  </div>
                </>
              )}
            </div>

            <TabsContent value="all" />
            <TabsContent value="unread" />
          </Tabs>
        </div>

        {/* 우측 다이제스트 패널 — lg에서 1/3 너비 */}
        {showDigest && (
          <div className="lg:col-span-1">
            <div className="rounded-lg border bg-card p-4">
              <h2 className="mb-4 text-sm font-semibold">주간 다이제스트</h2>
              <DigestPanel />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
