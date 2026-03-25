"""
[PM팀] 주간회의록 스프레드시트 → 프로젝트 관리 DB 임포트
260316 시트에서 프로젝트 + 마일스톤 + 배정인원 + 개요 데이터 파싱
"""
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.fund_table.db import get_db

# 로컬 JSON (이미 다운로드됨)
DATA_316 = os.path.join(os.path.dirname(__file__), '..', 'data', 'pm_sheet_260316.json')
DATA_312 = os.path.join(os.path.dirname(__file__), '..', 'data', 'pm_sheet_260312.json')


def _clean(s):
    """줄바꿈 → 공백, 양쪽 공백 제거"""
    return ' '.join(str(s).replace('\n', ' ').split()).strip()


def _parse_int(s):
    """콤마 포함 숫자 파싱"""
    try:
        return int(str(s).replace(',', '').replace(' ', '').strip())
    except (ValueError, TypeError):
        return 0


def parse_projects_316(data):
    """260316 시트에서 프로젝트 파싱"""
    # 프로젝트 시작 행 찾기 (col B=숫자, col C=이름)
    proj_starts = []
    for i, row in enumerate(data):
        if len(row) > 2 and row[1].strip().isdigit() and row[2].strip():
            proj_starts.append(i)

    projects = []
    seen_names = set()

    for idx, start in enumerate(proj_starts):
        end = proj_starts[idx + 1] if idx + 1 < len(proj_starts) else len(data)
        raw_name = _clean(data[start][2])

        # 중복 제거 (같은 이름의 두 번째 등장 스킵)
        # 단, 이름이 살짝 다르면 별도 프로젝트
        dedup_key = raw_name.replace(' ', '')
        if dedup_key in seen_names:
            continue
        seen_names.add(dedup_key)

        proj = parse_one_project(data, start, end, raw_name)
        projects.append(proj)

    return projects


def parse_one_project(data, start, end, name):
    """하나의 프로젝트 블록 파싱"""
    proj = {
        'name': name,
        'members': [],
        'milestones': [],
        'overview': {},
        'collections': [],
    }

    # 배정인원 (col D=역할, col E=이름)
    role_map = {
        'PM': 'PM', '공간': '공간', '시공': '시공', '미술': '미술',
        '시각': '시각', '파머스': '파머스', '개발': '개발', '운영': '운영'
    }

    for r in range(start, end):
        row = data[r]
        if len(row) < 5:
            continue

        role = row[3].strip()
        member_name = row[4].strip()

        # 배정인원
        if role in role_map and member_name:
            # 추가 담당자 (col F)
            extra = row[5].strip() if len(row) > 5 else ''
            full_name = f"{member_name}, {extra}" if extra and extra not in member_name else member_name
            proj['members'].append({'role': role, 'name': full_name})

        # 기본정보
        if role == '위치' and member_name:
            proj['overview']['location'] = member_name
        elif role == '용도' and member_name:
            proj['overview']['usage'] = member_name
        elif role == '규모' and member_name:
            proj['overview']['scale'] = member_name
        elif '연면적' in role and member_name:
            # 연면적 데이터 - 첫 번째만 area_pyeong에
            try:
                area = float(member_name.replace(',', ''))
                if not proj['overview'].get('area_pyeong'):
                    proj['overview']['area_pyeong'] = area
            except ValueError:
                pass
        elif role == '프로젝트 카테고리' and member_name:
            proj['overview']['project_category'] = member_name

        # 마일스톤 (col H=이름, col J=체크, col K=날짜)
        if len(row) > 9:
            ms_name = row[7].strip()
            ms_check = row[9].strip()
            ms_date = row[10].strip() if len(row) > 10 else ''

            if ms_name and ms_name not in ('일정\n체크', '일정 체크', ''):
                # 이미 등록된 마일스톤인지 확인
                if not any(m['name'] == ms_name for m in proj['milestones']):
                    proj['milestones'].append({
                        'name': ms_name,
                        'completed': 1 if ms_check == 'TRUE' else 0,
                        'date': ms_date if ms_date else ''
                    })

        # 수금현황 (col N~, 260316 특유 컬럼 구조)
        # 설계/시공/브랜드 등 카테고리별 수금 데이터
        if len(row) > 15:
            col_n = row[13].strip() if len(row) > 13 else ''
            col_o = row[14].strip() if len(row) > 14 else ''

            # 수금 데이터 파싱 (계약 체결일, 총 계약금 등)
            if col_n == '총 계약금' and col_o:
                proj['overview']['design_contract_amount'] = _parse_int(col_o)
            elif col_n == '수금 계' and col_o:
                # 설계 수금계
                pass

    # 이슈사항 (col N에서 이슈 관련)
    for r in range(start, end):
        row = data[r]
        if len(row) < 15:
            continue
        issue_label = row[13].strip()
        issue_val = row[14].strip() if len(row) > 14 else ''

        if '이슈' in str(row[12]) if len(row) > 12 else False:
            pass  # 이슈 섹션 시작
        if issue_label == '디자인/인허가':
            proj['overview']['issue_design'] = issue_val
        elif issue_label == '일정':
            # 일정 이슈는 여러 컬럼에 걸쳐있을 수 있음
            vals = [issue_val]
            for c in range(15, min(len(row), 22)):
                if row[c].strip():
                    vals.append(row[c].strip())
            proj['overview']['issue_schedule'] = ' / '.join(v for v in vals if v)
        elif issue_label == '예산':
            vals = [issue_val]
            for c in range(15, min(len(row), 22)):
                if row[c].strip():
                    vals.append(row[c].strip())
            proj['overview']['issue_budget'] = ' / '.join(v for v in vals if v)
        elif issue_label == '운영':
            vals = [issue_val]
            for c in range(15, min(len(row), 22)):
                if row[c].strip():
                    vals.append(row[c].strip())
            proj['overview']['issue_operation'] = ' / '.join(v for v in vals if v)
        elif issue_label == '하자':
            proj['overview']['issue_defect'] = issue_val
        elif issue_label == '기타':
            proj['overview']['issue_other'] = issue_val
        elif issue_label == '메뉴개발':
            # 메뉴개발 이슈도 기타에 추가
            if issue_val:
                existing = proj['overview'].get('issue_other', '')
                proj['overview']['issue_other'] = f"{existing} / 메뉴개발: {issue_val}".strip(' /')

    return proj


def supplement_from_312(projects_316, data_312):
    """260312 시트에서 추가 데이터 보충 (계약 금액, 일정 등)"""
    # 260312 프로젝트 시작 행
    proj_starts = []
    for i, row in enumerate(data_312):
        if len(row) > 2 and row[1].strip().isdigit() and row[2].strip():
            proj_starts.append(i)

    proj_312 = {}
    for idx, start in enumerate(proj_starts):
        end = proj_starts[idx + 1] if idx + 1 < len(proj_starts) else len(data_312)
        raw_name = _clean(data_312[start][2])
        proj_312[raw_name.replace(' ', '')] = (start, end)

    for proj in projects_316:
        key = proj['name'].replace(' ', '')
        if key not in proj_312:
            continue

        start, end = proj_312[key]
        ov = proj['overview']

        for r in range(start, end):
            row = data_312[r]
            if len(row) < 9:
                continue

            # col G(6)=라벨, col I(8)=값
            label = row[6].strip() if len(row) > 6 else ''
            val = row[8].strip() if len(row) > 8 else ''

            if label == '디자인 시작일' and val:
                ov['design_start'] = val
            elif label == '디자인 종료일' and val:
                ov['design_end'] = val
            elif label == '시공 시작일' and val:
                ov['construction_start'] = val
            elif label == '시공 종료일' and val:
                ov['construction_end'] = val
            elif label == '오픈 예정일' and val:
                ov['open_date'] = val
            elif label == '현재 진행상황' and val:
                ov['current_status'] = val
            elif label == '설계 계약일자' and val:
                ov['design_contract_date'] = val
            elif label == '설계 계약금액' and val:
                ov['design_contract_amount'] = _parse_int(val)
            elif label == '시공 계약일자' and val:
                ov['construction_contract_date'] = val
            elif label.startswith('시공 계약금액') and val:
                ov['construction_contract_amount'] = _parse_int(val)
            elif label == '예상 수익률' and val:
                try:
                    ov['profit_rate'] = float(val.replace('%', '').strip())
                except ValueError:
                    pass

        # 260312 수금현황 (col K~M)
        for r in range(start, end):
            row = data_312[r]
            if len(row) < 13:
                continue
            stage = row[11].strip() if len(row) > 11 else ''
            amount_str = row[12].strip() if len(row) > 12 else ''
            condition = row[13].strip() if len(row) > 13 else ''

            if stage and amount_str:
                amount = _parse_int(amount_str)
                if amount > 0:
                    proj['collections'].append({
                        'stage': stage,
                        'amount': amount,
                        'condition': condition
                    })


def insert_to_db(projects):
    """DB에 프로젝트 추가"""
    conn = get_db()
    inserted = 0
    skipped = 0

    for proj in projects:
        name = proj['name']
        ov = proj['overview']

        # 이미 존재하는 프로젝트는 스킵
        existing = conn.execute('SELECT id FROM projects WHERE name = ?', (name,)).fetchone()
        if existing:
            print(f'  SKIP (이미 존재): {name}')
            skipped += 1
            continue

        # 등급 추정 (카테고리 기반)
        cat = ov.get('project_category', '')
        if '직영' in cat:
            grade = '1등급'
        elif '시공' in cat and '설계' in cat:
            grade = '2등급'
        elif '설계' in cat:
            grade = '3등급'
        else:
            grade = '4등급'

        # projects 테이블
        design_amt = ov.get('design_contract_amount', 0)
        constr_amt = ov.get('construction_contract_amount', 0)

        cur = conn.execute('''
            INSERT INTO projects (name, description, design_amount, construction_amount,
                                  profit_rate, status, grade, sort_order)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        ''', (
            name,
            ov.get('project_category', ''),
            design_amt,
            constr_amt,
            ov.get('profit_rate', 0),
            grade,
            inserted + 1
        ))
        project_id = cur.lastrowid

        # project_overview 테이블
        conn.execute('''
            INSERT INTO project_overview (
                project_id, project_category, location, usage, scale, area_pyeong,
                design_start, design_end, construction_start, construction_end, open_date,
                current_status, design_contract_date, design_contract_amount,
                construction_contract_date, construction_contract_amount,
                issue_design, issue_schedule, issue_budget, issue_operation,
                issue_defect, issue_other
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            project_id,
            ov.get('project_category', ''),
            ov.get('location', ''),
            ov.get('usage', ''),
            ov.get('scale', ''),
            ov.get('area_pyeong', 0),
            ov.get('design_start', ''),
            ov.get('design_end', ''),
            ov.get('construction_start', ''),
            ov.get('construction_end', ''),
            ov.get('open_date', ''),
            ov.get('current_status', ''),
            ov.get('design_contract_date', ''),
            ov.get('design_contract_amount', 0),
            ov.get('construction_contract_date', ''),
            ov.get('construction_contract_amount', 0),
            ov.get('issue_design', ''),
            ov.get('issue_schedule', ''),
            ov.get('issue_budget', ''),
            ov.get('issue_operation', ''),
            ov.get('issue_defect', ''),
            ov.get('issue_other', ''),
        ))

        # 마일스톤
        for i, ms in enumerate(proj['milestones']):
            conn.execute('''
                INSERT INTO project_milestones (project_id, name, completed, date, sort_order)
                VALUES (?, ?, ?, ?, ?)
            ''', (project_id, ms['name'], ms['completed'], ms['date'], i))

        # 배정인원
        for i, m in enumerate(proj['members']):
            conn.execute('''
                INSERT INTO project_members (project_id, role, name, sort_order)
                VALUES (?, ?, ?, ?)
            ''', (project_id, m['role'], m['name'], i))

        # 수금현황
        for coll in proj['collections']:
            # 카테고리 추정 (설계/시공)
            stage = coll['stage']
            category = '설계' if '설계' in stage else '시공' if '시공' in stage else '기타'
            conn.execute('''
                INSERT INTO collections (project_id, category, stage, amount, collected)
                VALUES (?, ?, ?, ?, 0)
            ''', (project_id, category, stage, coll['amount']))

        inserted += 1
        ms_count = len(proj['milestones'])
        mem_count = len(proj['members'])
        coll_count = len(proj['collections'])
        print(f'  ✓ {name} (마일스톤 {ms_count}, 인원 {mem_count}, 수금 {coll_count})')

    conn.commit()
    conn.close()
    return inserted, skipped


def main():
    print('=== PM팀 주간회의록 → 프로젝트 관리 DB 임포트 ===\n')

    # 데이터 로드
    with open(DATA_316) as f:
        data_316 = json.load(f)
    with open(DATA_312) as f:
        data_312 = json.load(f)

    # 260316에서 파싱
    print('[1/3] 260316 시트 파싱...')
    projects = parse_projects_316(data_316)
    print(f'  → {len(projects)}개 프로젝트 (중복 제거)')

    # 260312에서 보충
    print('[2/3] 260312 시트에서 보충 데이터...')
    supplement_from_312(projects, data_312)

    # DB 삽입
    print(f'\n[3/3] DB 삽입...')
    inserted, skipped = insert_to_db(projects)

    print(f'\n완료: {inserted}개 추가, {skipped}개 스킵')


if __name__ == '__main__':
    main()
