"""
Excel → 계약서 일괄 생성 CLI

사용:
  python scripts/generate_contracts_from_excel.py data/계약서_입력양식.xlsx
  python scripts/generate_contracts_from_excel.py data/계약서_입력양식.xlsx --out data/contracts/
"""
import sys
import argparse
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.contracts.contract_generator import generate_from_excel

def main():
    parser = argparse.ArgumentParser(description="Excel → 계약서 일괄 생성")
    parser.add_argument("excel", help="Excel 입력양식 파일 경로")
    parser.add_argument("--out", default=None, help="출력 폴더 (기본: Excel 파일과 같은 폴더의 contracts/)")
    args = parser.parse_args()

    excel_path = pathlib.Path(args.excel)
    if not excel_path.exists():
        print(f"❌ 파일 없음: {excel_path}")
        sys.exit(1)

    out_dir = args.out or str(excel_path.parent / "contracts")
    print(f"📄 입력: {excel_path}")
    print(f"📁 출력 폴더: {out_dir}")
    print("처리 중...\n")

    results = generate_from_excel(str(excel_path), out_dir)

    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] == "error"]

    for r in ok:
        print(f"  ✅ {r['file']}")
    for r in err:
        print(f"  ❌ {r['file']}: {r['msg']}")

    print(f"\n완료: {len(ok)}건 생성, {len(err)}건 실패")
    if ok:
        print(f"저장 위치: {out_dir}/")

if __name__ == "__main__":
    main()
