"""
기존 단일 사용자(tgjeon)를 새 users DB에 마이그레이션하는 스크립트.
.env의 GW_USER_ID/GW_USER_PW를 DB에 등록하고 emp_seq, dept_seq 설정.
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.user_db import register, update_profile, get_user


def main():
    print("=" * 50)
    print("기존 사용자 마이그레이션 (tgjeon → users.db)")
    print("=" * 50)

    # 이미 등록되었는지 확인
    existing = get_user("tgjeon")
    if existing:
        print(f"이미 등록된 사용자: {existing}")
        print("프로필 업데이트만 실행합니다.")
    else:
        # .env에서 비밀번호 가져오기
        import os
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / "config" / ".env")

        gw_pw = os.getenv("GW_USER_PW")
        if not gw_pw:
            print("ERROR: config/.env에 GW_USER_PW가 없습니다.")
            return

        result = register(
            gw_id="tgjeon",
            gw_pw=gw_pw,
            name="전태규",
            position="대리",
        )
        print(f"등록 결과: {result}")

    # emp_seq, dept_seq 설정
    result = update_profile(
        "tgjeon",
        emp_seq="2922",
        dept_seq="2017",
        email_addr="tgjeon",
    )
    print(f"프로필 업데이트: {result}")

    # 확인
    user = get_user("tgjeon")
    print(f"\n최종 사용자 정보:")
    for k, v in user.items():
        print(f"  {k}: {v}")

    print("\n마이그레이션 완료!")


if __name__ == "__main__":
    main()
