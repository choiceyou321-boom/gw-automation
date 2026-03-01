"""
챗봇 서버 실행 스크립트
사용법: python run_chatbot.py
"""
import os
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# 환경 변수 로드 (.env)
from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

# GEMINI_API_KEY 확인
if not os.environ.get("GEMINI_API_KEY"):
    print("[오류] GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    print("  방법 1: config/.env 파일에 GEMINI_API_KEY=... 추가")
    print("  방법 2: https://aistudio.google.com/apikey 에서 무료 발급")
    sys.exit(1)

print("=" * 50)
print("  GW 자동화 챗봇 서버 시작")
print("=" * 50)
PORT = 51749

print(f"  URL: http://localhost:{PORT}")
print(f"  API: http://localhost:{PORT}/docs")
print("=" * 50)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.chatbot.app:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info"
    )
