#!/usr/bin/env python3
"""
기존 사용자 GW 자격 증명 검증 스크립트 (1회성)

전체 사용자 목록을 순회하며 GW 로그인 시도.
실패한 사용자를 보고하고, --delete 플래그가 있을 때만 실제 삭제.
관리자 계정(is_admin=1)은 항상 건너뜀.

사용법:
  .venv/bin/python scripts/validate_existing_users.py             # 보고만 (dry-run)
  .venv/bin/python scripts/validate_existing_users.py --delete    # 유효하지 않은 계정 삭제
"""
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "config" / ".env")

from src.auth.user_db import list_users, get_decrypted_password, delete_user
from src.auth.login import validate_gw_credentials


def main():
    do_delete = "--delete" in sys.argv

    print("=" * 60)
    print("GW 사용자 자격 증명 검증 스크립트")
    print(f"모드: {'삭제' if do_delete else '보고만 (dry-run)'}")
    print("=" * 60)

    users = list_users()
    if not users:
        print("등록된 사용자가 없습니다.")
        return

    print(f"검증 대상: {len(users)}명\n")

    valid_count = 0
    invalid_count = 0
    error_count = 0
    skipped_count = 0
    invalid_users = []

    for i, user in enumerate(users, 1):
        gw_id = user["gw_id"]
        name = user.get("name", "")
        is_admin = user.get("is_admin", 0)

        # 관리자 계정 건너뜀
        if is_admin:
            print(f"[{i}/{len(users)}] {gw_id} ({name}) — 관리자 계정, 건너뜀")
            skipped_count += 1
            continue

        # 비밀번호 복호화
        pw = get_decrypted_password(gw_id)
        if not pw:
            print(f"[{i}/{len(users)}] {gw_id} ({name}) — 비밀번호 복호화 실패")
            error_count += 1
            continue

        print(f"[{i}/{len(users)}] {gw_id} ({name}) — 검증 중...", end=" ", flush=True)

        try:
            result = validate_gw_credentials(gw_id, pw)
        except Exception as e:
            print(f"오류 ({e})")
            error_count += 1
            continue

        if result.get("valid"):
            print("유효")
            valid_count += 1
        else:
            error_msg = result.get("error", "알 수 없음")
            print(f"무효 ({error_msg})")
            invalid_count += 1
            invalid_users.append({"gw_id": gw_id, "name": name, "error": error_msg})

            if do_delete:
                delete_user(gw_id)
                # 세션 캐시 무효화
                try:
                    from src.auth.session_manager import invalidate_cache
                    invalidate_cache(gw_id)
                except Exception:
                    pass
                print(f"  → 삭제 완료: {gw_id}")

        # GW 서버 부하 방지: 검증 사이 3초 대기
        if i < len(users):
            time.sleep(3)

    # 결과 요약
    print("\n" + "=" * 60)
    print("검증 결과 요약")
    print("=" * 60)
    print(f"  전체: {len(users)}명")
    print(f"  유효: {valid_count}명")
    print(f"  무효: {invalid_count}명" + (f" (삭제됨)" if do_delete else " (보고만)"))
    print(f"  오류: {error_count}명 (복호화 실패)")
    print(f"  건너뜀: {skipped_count}명 (관리자)")

    if invalid_users:
        print(f"\n무효 사용자 목록:")
        for u in invalid_users:
            status = "삭제됨" if do_delete else "미조치"
            print(f"  - {u['gw_id']} ({u['name']}): {u['error']} [{status}]")

    if invalid_users and not do_delete:
        print(f"\n실제 삭제하려면: python scripts/validate_existing_users.py --delete")


if __name__ == "__main__":
    main()
