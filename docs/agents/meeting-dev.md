# meeting-dev (회의실 예약)

## 기본 정보
- **역할**: 회의실 예약 자동화 모듈 개발
- **모델**: Claude Sonnet 4.6
- **에이전트 타입**: general-purpose

## 담당 업무
1. **회의실 예약 자동화**: Playwright로 그룹웨어 회의실 예약
2. **회의실 조회**: 목록 조회, 예약 현황, 빈 시간대 검색
3. **네트워크 분석**: 그룹웨어 내부 API 패턴 캡처

## 주요 작업 이력
- `src/meeting/reservation.py` 개발 완료 (~938 라인)
- 주요 기능 구현:
  - `navigate_to_meeting_room()` - 회의실 메뉴 이동
  - `get_meeting_rooms()` - 회의실 목록 조회
  - `get_reservations()` - 예약 현황 확인
  - `find_available_slots()` - 빈 시간대 검색
  - `make_reservation()` - 예약 등록
- 네트워크 인터셉트(`_setup_network_intercept`)로 API 패턴 캡처
- 임포트 테스트 통과

## 담당 파일
- `src/meeting/reservation.py` - 회의실 예약 전체 모듈

## 연동 상태
- 챗봇 `agent.py`의 `handle_reserve_meeting_room()`에서 호출됨
- ThreadPoolExecutor로 async/sync 충돌 해결됨
- 실제 그룹웨어 테스트 필요 (로그인 모듈 수정 중)
