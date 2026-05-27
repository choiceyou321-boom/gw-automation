import { api } from '@/lib/api-client'

/** FastAPI /api/auth/me 응답 (백엔드 src/shared/auth 참고) */
export interface Me {
  user_id: string
  user_name?: string
  is_admin?: boolean
  // 백엔드 응답 스키마 확정 시 openapi-typescript로 자동 생성 교체
}

// 백엔드 FastAPI는 /auth/* (prefix 없음). v5에서는 같은 origin이므로 그대로 호출.
export function fetchMe(): Promise<Me> {
  return api.get<Me>('/auth/me')
}
