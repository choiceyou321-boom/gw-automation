# 다음 세션 시작 프롬프트 — 레거시 (gw-automation)

복사해서 다음 세션 첫 메시지에 붙여넣기:

```
이 리포는 레거시 GW 자동화 (gw-automation). PM 트랙은 별도 리포 glow-pm 으로 분리 완료 (2026-05-28).
v9.1에서 PM UI 진입점/링크 전부 제거 완료 — 이 리포는 챗봇 + GW 자동화 전담.

# 호칭
- 글로우 PM = 별도 리포 /Users/tg_mac_mini/Documents/glow-pm (https://github.com/choiceyou321-boom/glow-pm)
- 레거시 챗봇 = 이 리포의 / (src/chatbot/static/index.html)
- 레거시 GW 자동화 = src/gw/ + src/office/ + src/pm/fund_table/ (API only)

# 현재 상태
- master HEAD: a868f89 (PR #32 v9.1 PM UI 제거 + 챗봇 도구 정리 머지)
- 머지된 PR 합계: v5.0~v9.1 = 32개
- pytest 326 PASS (중복 9개 정리됨 — 클린)
- 챗봇 도구: 34종 (스키마=핸들러 정합)
- 서버: .venv/bin/python run_chatbot.py → :51749

# v9.1 적용 사항 (이번 세션)
- frontend/ 디렉토리 완전 삭제
- src/pm/static/fund.{html,js,css} 삭제
- src/chatbot/app.py: /pm-v2, /pm-static, pages_router 마운트 제거, /guide만 챗봇 라우터로 이관
- src/pm/fund_table/routes.py: pages_router(/fund, /guide, /insights) 제거 (빈 라우터 호환 가드 유지)
- 챗봇 인덱스의 "프로젝트 관리" 버튼 제거
- 챗봇 응답 문구 "/fund 페이지" → "글로우 PM (별도 앱)" 일괄 치환
- guide.html PM 섹션 → 글로우 PM 안내로 정리
- tools_schema 미연결 5종 제거 (save_contact_from_image, list_contacts, issue/list/cancel_tax_invoice) — _DEFERRED_OFFICE_TOOLS_v9_1 로 보존, 핸들러 구현 시 재도입

# 백엔드 유지 자산
- src/pm/fund_table/ — DB + API (챗봇 도구가 의존: get_project_schedule 등)
- /api/pm/*, /api/fund/* endpoint
- src/office/crm/, src/office/tax_invoice/ — 향후 핸들러 구현용
- users.db, fund_management.db

# 다음 작업 후보 (사용자 선택)
1. 챗봇 스트리밍(SSE) — 응답 토큰 실시간 표시 + 도구 호출 단계 가시화
2. Office 핸들러 구현 → 5종 도구 재도입 (CRM 명함 OCR + 세금계산서)
3. GW Track A 시연 — scripts/track_a_capture.py 사용자 시연 후 selectors.py 머지
4. GW 신규 모듈(PER/BUDGET/LOG/SAL/PUR) 진입 자동화
5. 운영 배포 — Docker + nginx (레거시 + glow-pm 분리 배포)
6. 챗봇 도구 e2e 테스트 보강 — 34종 각 정상 작동 검증

# 참고 문서
- docs/HANDOFF_2026-05-28_glow_pm_split.md ← 분리 시점 전체 컨텍스트 (먼저 읽기)
- docs/ARCHITECTURE_v5.md
- docs/HANDOFF_v5_kickoff.md (구버전)

# 진행 방식
1) docs/HANDOFF_2026-05-28_glow_pm_split.md 먼저 읽기
2) 사용자에게 다음 작업 1~6 중 무엇인지 묻기 (또는 자율 추천 채택)
3) 브랜치 + PR + 머지 패턴 그대로
```

## 검증 명령 (세션 시작 시)

```bash
cd "/Users/tg_mac_mini/Documents/자동화 work"
git log --oneline -3   # a868f89 (v9.1)
.venv/bin/python -m pytest -q --tb=no   # 326 passed
PYTHONPATH=. .venv/bin/python -c "
from src.chatbot.tools_schema import AUTOMATION_TOOLS
from src.chatbot.handlers import TOOL_HANDLERS
s = {fd.name for t in AUTOMATION_TOOLS for fd in t.function_declarations}
h = set(TOOL_HANDLERS.keys())
print(f'schema={len(s)} handlers={len(h)} match={s==h}')
"   # schema=34 handlers=34 match=True
.venv/bin/python run_chatbot.py         # :51749 기동
```
