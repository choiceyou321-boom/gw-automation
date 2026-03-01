# chatbot-dev (챗봇 개발)

## 기본 정보
- **역할**: 웹 챗봇 인터페이스 및 AI 연동 개발
- **모델**: Claude Sonnet 4.6
- **에이전트 타입**: general-purpose

## 담당 업무
1. **웹 UI**: 채팅 인터페이스, 파일 드래그앤드롭
2. **FastAPI 백엔드**: API 서버, 세션 관리, 대화 기록
3. **AI 연동**: Gemini API 연동, 의도 분석, function calling

## 주요 작업 이력
- `src/chatbot/app.py` - FastAPI 백엔드 개발 완료
- `src/chatbot/agent.py` - AI 에이전트 개발 (Anthropic → Gemini 전환)
- `src/chatbot/static/` - 프론트엔드 UI 개발 완료
- `run_chatbot.py` - 서버 실행 스크립트

## 담당 파일
- `src/chatbot/app.py` - FastAPI 앱 (라우트: /, /chat, /upload, /history)
- `src/chatbot/agent.py` - Gemini 연동 + 의도 분석 + function calling
- `src/chatbot/static/index.html` - 다크 테마 채팅 UI
- `src/chatbot/static/style.css` - 반응형 스타일
- `src/chatbot/static/app.js` - 파일 첨부, 메시지 송수신
- `run_chatbot.py` - 서버 실행 (port 51749)

## 기술 스택
- **백엔드**: FastAPI + uvicorn
- **AI**: Google Gemini 2.5 Flash (function calling)
- **프론트**: 바닐라 HTML/CSS/JS (다크 테마)
- **실행**: `python run_chatbot.py` → http://localhost:51749

## 주요 해결 이슈
1. Anthropic API 크레딧 부족 → Gemini 무료 API로 전환
2. `functions` → `function_declarations` 파라미터 수정
3. Playwright sync + asyncio 충돌 → ThreadPoolExecutor 사용
4. 자연어 이해 부족 → 시스템 프롬프트에 한국어 날짜/시간 변환 규칙 추가
