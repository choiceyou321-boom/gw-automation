#!/usr/bin/env python3
"""
PDF 한글→영문 번역 스크립트 (v2)
- pymupdf 텍스트 블록 기반 그룹핑
- Gemini 2.5 Flash로 공간 제약 고려한 간결 번역
- 최소 폰트 크기 보장 (본문 9pt, 제목 16pt)
- 다중 포인트 배경색 샘플링
- insert_textbox 기반 텍스트 배치
"""

import os
import sys
import json
import time
import fitz  # pymupdf
from pathlib import Path
from functools import partial

# stdout 버퍼링 방지
print = partial(print, flush=True)

PROJECT_ROOT = Path(__file__).parent.parent
PDF_PATH = PROJECT_ROOT / "test 자료" / "TalkFile_대한피부건강산업협회 소개(26.03.01).pdf.pdf"
OUTPUT_DIR = PROJECT_ROOT / "data" / "kshia_translation"
OUTPUT_PDF = OUTPUT_DIR / "KSHIA_Introduction_EN.pdf"
TRANS_CACHE = OUTPUT_DIR / "translated_results.json"
GEMINI_CACHE = OUTPUT_DIR / "gemini_block_translations.json"

# 폰트 크기 제한
MIN_BODY_FONT = 12.0
MIN_HEADING_FONT = 22.0
HEADING_THRESHOLD = 40.0  # 원본 크기가 이 이상이면 제목으로 취급

# 영문 문자 평균 폭 비율 (Helvetica 기준, fontsize 대비)
CHAR_WIDTH_RATIO = 0.52


def load_env():
    """config/.env에서 API 키 로드"""
    env_path = PROJECT_ROOT / "config" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


load_env()

import google.generativeai as genai
genai.configure(api_key=os.environ["GEMINI_API_KEY"])


# ─── 텍스트 감지 유틸 ───

def has_cjk(text):
    """한글 또는 중국어(한자) 포함 여부"""
    for c in text:
        if '\uac00' <= c <= '\ud7a3':  # 한글 음절
            return True
        if '\u3131' <= c <= '\u3163':  # 한글 자모
            return True
        if '\u4e00' <= c <= '\u9fff':  # CJK 통합 한자
            return True
        if '\u3400' <= c <= '\u4dbf':  # CJK 확장 A
            return True
    return False


def is_mostly_english(text):
    """텍스트가 대부분 영어/숫자/기호인지"""
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / max(len(text), 1) > 0.8


# ─── 텍스트 블록 추출 및 그룹핑 ───

def extract_text_blocks(page):
    """페이지에서 텍스트 블록을 추출하고 논리적으로 그룹화"""
    blocks = page.get_text("dict")["blocks"]
    result = []

    for block in blocks:
        if block["type"] != 0:
            continue

        lines_data = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            line_text = ""
            line_spans = []
            for span in spans:
                if span["text"].strip():
                    line_text += span["text"]
                    line_spans.append(span)
            if line_text.strip():
                lines_data.append({
                    "text": line_text.strip(),
                    "bbox": list(line["bbox"]),
                    "spans": line_spans,
                })

        if not lines_data:
            continue

        # 블록 내 라인들을 서브그룹으로 분리
        # 같은 블록 내에서도 폰트 크기가 크게 다르면 분리
        sub_groups = []
        current_group = [lines_data[0]]

        for i in range(1, len(lines_data)):
            prev_line = current_group[-1]
            curr_line = lines_data[i]

            prev_size = prev_line["spans"][0]["size"] if prev_line["spans"] else 0
            curr_size = curr_line["spans"][0]["size"] if curr_line["spans"] else 0

            # 폰트 크기 차이가 크면 분리 (제목 vs 본문)
            size_diff = abs(prev_size - curr_size)
            # 수직 간격이 라인 높이의 2배 이상이면 분리
            gap = curr_line["bbox"][1] - prev_line["bbox"][3]
            line_height = prev_line["bbox"][3] - prev_line["bbox"][1]

            if size_diff > 10 or gap > line_height * 2.0:
                sub_groups.append(current_group)
                current_group = [curr_line]
            else:
                current_group.append(curr_line)

        if current_group:
            sub_groups.append(current_group)

        # 각 서브그룹을 하나의 텍스트 블록으로
        for group in sub_groups:
            x0 = min(l["bbox"][0] for l in group)
            y0 = min(l["bbox"][1] for l in group)
            x1 = max(l["bbox"][2] for l in group)
            y1 = max(l["bbox"][3] for l in group)
            full_text = "\n".join(l["text"] for l in group)

            first_span = group[0]["spans"][0]
            avg_size = sum(l["spans"][0]["size"] for l in group) / len(group)

            # 볼드 여부 판단
            font_name = first_span["font"]
            is_bold = any(kw in font_name for kw in ["Bold", "ExtraBo", "Semibold", "Heavy"])

            result.append({
                "text": full_text,
                "bbox": [x0, y0, x1, y1],
                "lines": group,
                "font_size": avg_size,
                "color": first_span["color"],
                "font": font_name,
                "is_bold": is_bold,
                "needs_translation": has_cjk(full_text) and not is_mostly_english(full_text),
            })

    return result


# ─── 배경색 샘플링 ───

def sample_bg_color_multi(pixmap, bbox, scale):
    """텍스트 영역 주변 여러 지점에서 배경색 샘플링 (중앙값 사용)"""
    x0, y0, x1, y1 = [int(v * scale) for v in bbox]

    # 클램핑
    def clamp_x(x):
        return max(0, min(x, pixmap.width - 1))
    def clamp_y(y):
        return max(0, min(y, pixmap.height - 1))

    # 여러 샘플 포인트: 위쪽, 좌측, 우측, 좌상, 우상
    sample_points = [
        (clamp_x((x0 + x1) // 2), clamp_y(y0 - 5)),   # 위쪽 중앙
        (clamp_x(x0 - 5), clamp_y((y0 + y1) // 2)),     # 좌측
        (clamp_x(x1 + 5), clamp_y((y0 + y1) // 2)),     # 우측
        (clamp_x(x0 - 3), clamp_y(y0 - 3)),              # 좌상
        (clamp_x(x1 + 3), clamp_y(y0 - 3)),              # 우상
        (clamp_x((x0 + x1) // 2), clamp_y(y1 + 5)),     # 아래쪽 중앙
        (clamp_x(x0 - 5), clamp_y(y0 - 5)),              # 좌상 확장
    ]

    colors = []
    for sx, sy in sample_points:
        try:
            pixel = pixmap.pixel(sx, sy)
            colors.append(pixel[:3])
        except Exception:
            continue

    if not colors:
        return (1.0, 1.0, 1.0)  # 기본 흰색

    # 중앙값 사용 (이상치에 강건)
    colors.sort(key=lambda c: sum(c))
    mid = len(colors) // 2
    r, g, b = colors[mid]
    return (r / 255.0, g / 255.0, b / 255.0)


# ─── Gemini 번역 ───

def _build_block_info(text_blocks):
    """번역 필요 블록의 공간 제약 정보 생성"""
    blocks_to_translate = []
    for i, block in enumerate(text_blocks):
        if not block["needs_translation"]:
            continue

        bbox = block["bbox"]
        width_px = bbox[2] - bbox[0]
        font_size = block["font_size"]
        min_font = MIN_HEADING_FONT if font_size > HEADING_THRESHOLD else MIN_BODY_FONT
        effective_font = max(font_size * 0.7, min_font)
        chars_per_line = int(width_px / (effective_font * CHAR_WIDTH_RATIO))
        num_lines = len(block["lines"])
        max_chars = chars_per_line * max(num_lines, 1)

        blocks_to_translate.append({
            "idx": i,
            "text": block["text"],
            "font_size": round(font_size, 1),
            "width_px": round(width_px, 0),
            "max_chars": max_chars,
            "chars_per_line": chars_per_line,
            "num_lines": num_lines,
        })
    return blocks_to_translate


def _get_page_ref(page_num, existing_translations):
    """기존 번역 참조 텍스트 추출"""
    if page_num >= len(existing_translations):
        return ""
    page_data = existing_translations[page_num]
    sections = page_data.get("sections", [])
    ref_texts = []
    for sec in sections[:15]:
        content = sec.get("content", "")
        if isinstance(content, str):
            ref_texts.append(content[:200])
        elif isinstance(content, dict):
            ref_texts.append(str(content)[:200])
        elif isinstance(content, list):
            for item in content[:3]:
                if isinstance(item, str):
                    ref_texts.append(item[:100])
                elif isinstance(item, dict):
                    ref_texts.append(str(item)[:100])
    return "\n".join(ref_texts[:20])


def _parse_gemini_json(text):
    """Gemini 응답에서 JSON 배열 파싱 (에러 복구 포함)"""
    # 정상 파싱 시도
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # JSON 배열 부분 추출
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 개별 객체씩 추출 시도
    import re
    results = []
    for match in re.finditer(r'\{\s*"block_idx"\s*:\s*(\d+)\s*,\s*"english"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', text):
        try:
            idx = int(match.group(1))
            eng = match.group(2).replace('\\"', '"').replace('\\n', '\n')
            results.append({"block_idx": idx, "english": eng})
        except (ValueError, IndexError):
            continue

    return results


def _call_gemini_batch(blocks_batch, page_num, page_ref):
    """Gemini API 호출 (단일 배치)"""
    blocks_desc = []
    for b in blocks_batch:
        blocks_desc.append(
            f'[Block {b["idx"]}] font_size={b["font_size"]}, '
            f'max_chars={b["max_chars"]}, chars_per_line={b["chars_per_line"]}, '
            f'lines={b["num_lines"]}\n'
            f'  Korean: "{b["text"][:150]}"'
        )

    prompt = f"""Translate these Korean/Chinese text blocks from PDF page {page_num + 1} to English.

SPACE CONSTRAINTS:
- Each block has max_chars and chars_per_line limits
- Translation MUST fit within max_chars total characters
- Be CONCISE: use abbreviations (Prof., Dir., Dept., Assoc., etc.)
- Names in Korean: romanize (e.g., 홍석경 → Seok-Gyeong Hong)
- Names in Chinese/English: keep as-is
- Multiple lines: separate with \\n

Blocks:
{chr(10).join(blocks_desc)}

Reference:
{page_ref[:1500]}

JSON array response format:
[{{"block_idx": N, "english": "translation"}}]

Rules: translate Korean/Chinese only, keep numbers/emails/URLs, be concise.
"""

    model = genai.GenerativeModel("gemini-2.5-flash")

    for attempt in range(3):
        try:
            response = model.generate_content(
                [prompt],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )

            mapping_list = _parse_gemini_json(response.text)
            result = {}
            for item in mapping_list:
                idx = item.get("block_idx")
                eng = item.get("english", "")
                if idx is not None and eng:
                    result[idx] = eng
            return result

        except Exception as e:
            print(f"    Gemini 배치 호출 실패 (시도 {attempt + 1}): {e}")
            if attempt < 2:
                time.sleep(3)

    return {}


# 배치 크기: 한 번에 번역할 최대 블록 수
BATCH_SIZE = 25


def translate_blocks_with_gemini(page_num, text_blocks, existing_translations):
    """Gemini로 텍스트 블록 번역 — 대규모 페이지는 배치 분할"""

    blocks_to_translate = _build_block_info(text_blocks)
    if not blocks_to_translate:
        return {}

    page_ref = _get_page_ref(page_num, existing_translations)

    # 배치 분할
    all_results = {}
    for batch_start in range(0, len(blocks_to_translate), BATCH_SIZE):
        batch = blocks_to_translate[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(blocks_to_translate) + BATCH_SIZE - 1) // BATCH_SIZE

        if total_batches > 1:
            print(f"    배치 {batch_num}/{total_batches} ({len(batch)}개 블록)")

        batch_result = _call_gemini_batch(batch, page_num, page_ref)
        all_results.update(batch_result)

        if batch_start + BATCH_SIZE < len(blocks_to_translate):
            time.sleep(2)  # 배치 간 대기

    return all_results


# ─── 폰트 크기 계산 ───

def calculate_font_size(english_text, bbox, original_size, is_bold):
    """영문 텍스트가 bbox에 맞도록 폰트 크기 계산"""
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    is_heading = original_size > HEADING_THRESHOLD
    min_font = MIN_HEADING_FONT if is_heading else MIN_BODY_FONT

    # 멀티라인 텍스트
    lines = english_text.split("\n")
    max_line_len = max(len(l) for l in lines)
    num_lines = len(lines)

    # 원본 크기에서 시작 (영어는 보통 한글보다 폭이 좁으므로 약간 줄임)
    # 한글 1자 ≈ 영어 1.5~2자 폭이므로, 원본 크기를 약간 유지
    target_size = original_size * 0.95

    # 너비 기반 계산: 가장 긴 줄이 들어갈 수 있는 크기
    if max_line_len > 0:
        size_by_width = width / (max_line_len * CHAR_WIDTH_RATIO)
        target_size = min(target_size, size_by_width)

    # 높이 기반 계산: 줄 수 고려
    line_height_ratio = 1.25
    if num_lines > 0:
        size_by_height = height / (num_lines * line_height_ratio)
        target_size = min(target_size, size_by_height)

    # 최소 크기 보장
    target_size = max(target_size, min_font)

    # 단, 원본보다 크게 하지 않음 (제목 제외)
    if not is_heading:
        target_size = min(target_size, original_size)

    return round(target_size, 1)


# ─── 페이지 처리 ───

def process_page(doc, page_num, page, existing_translations, gemini_cache):
    """한 페이지 처리: 텍스트 추출 → 번역 → redact → 삽입"""
    print(f"\n--- 페이지 {page_num + 1} 처리 중 ---")

    text_blocks = extract_text_blocks(page)
    kr_blocks = [(i, b) for i, b in enumerate(text_blocks) if b["needs_translation"]]

    print(f"  전체 블록: {len(text_blocks)}, 번역 필요: {len(kr_blocks)}")

    if not kr_blocks:
        print("  번역 불필요 — 건너뜀")
        return

    # Gemini 번역 (캐시 확인)
    cache_key = str(page_num)
    if cache_key in gemini_cache:
        print("  캐시된 번역 사용")
        mapping = {int(k): v for k, v in gemini_cache[cache_key].items()}
    else:
        mapping = translate_blocks_with_gemini(page_num, text_blocks, existing_translations)
        gemini_cache[cache_key] = {str(k): v for k, v in mapping.items()}
        # 캐시 저장
        with open(GEMINI_CACHE, "w") as f:
            json.dump(gemini_cache, f, ensure_ascii=False, indent=2)

    print(f"  번역 매핑: {len(mapping)}개")

    # 페이지 렌더링 (배경색 샘플링용)
    pixmap = page.get_pixmap(dpi=150)
    scale = pixmap.width / page.rect.width

    # 1단계: 원본 텍스트 영역 redact (배경색으로 덮기)
    for block_idx, block in kr_blocks:
        if block_idx not in mapping:
            continue

        # 블록의 각 라인을 개별적으로 redact
        for line_info in block["lines"]:
            bbox = line_info["bbox"]
            bg_color = sample_bg_color_multi(pixmap, bbox, scale)

            # redact 영역을 약간 확장하여 잔여 픽셀 제거
            pad_x = 3
            pad_y = 2
            rect = fitz.Rect(
                bbox[0] - pad_x,
                bbox[1] - pad_y,
                bbox[2] + pad_x,
                bbox[3] + pad_y
            )
            annot = page.add_redact_annot(rect)
            annot.set_colors(fill=bg_color)

    page.apply_redactions()
    print("  원본 텍스트 제거 완료")

    # 2단계: 영문 텍스트 삽입
    inserted = 0
    for block_idx, block in kr_blocks:
        if block_idx not in mapping:
            continue

        english_text = mapping[block_idx].strip()
        if not english_text:
            continue

        bbox = block["bbox"]
        original_size = block["font_size"]
        color_int = block["color"]
        is_bold = block["is_bold"]

        # 색상 변환 (int -> RGB float)
        r = ((color_int >> 16) & 0xFF) / 255.0
        g = ((color_int >> 8) & 0xFF) / 255.0
        b = (color_int & 0xFF) / 255.0

        # 폰트 선택
        fontname = "hebo" if is_bold else "helv"

        # 폰트 크기 계산
        font_size = calculate_font_size(english_text, bbox, original_size, is_bold)

        # textbox 영역 설정 — 높이를 필요 시 확장
        lines = english_text.split("\n")
        num_lines = len(lines)
        needed_height = num_lines * font_size * 1.3
        box_height = max(bbox[3] - bbox[1], needed_height)

        # textbox를 원본 bbox 위치에 배치 (높이만 확장 가능)
        text_rect = fitz.Rect(
            bbox[0],
            bbox[1],
            bbox[2],
            bbox[1] + box_height
        )

        # 정렬: 제목급은 가운데, 나머지는 좌측
        align = fitz.TEXT_ALIGN_CENTER if original_size > HEADING_THRESHOLD else fitz.TEXT_ALIGN_LEFT

        # textbox에 텍스트 삽입 시도
        rc = page.insert_textbox(
            text_rect,
            english_text,
            fontsize=font_size,
            fontname=fontname,
            color=(r, g, b),
            align=align,
        )

        # 공간 부족 시 폰트 줄이기
        if rc < 0:
            min_font = MIN_HEADING_FONT if original_size > HEADING_THRESHOLD else MIN_BODY_FONT
            for try_factor in [0.85, 0.75, 0.65, 0.55]:
                try_size = max(font_size * try_factor, min_font)
                # 높이 재계산
                try_lines = english_text.count("\n") + 1
                # insert_textbox는 자동 줄바꿈하므로 더 많은 줄이 생길 수 있음
                est_chars_per_line = int((bbox[2] - bbox[0]) / (try_size * CHAR_WIDTH_RATIO))
                if est_chars_per_line > 0:
                    est_lines = sum(
                        max(1, -(-len(l) // est_chars_per_line))
                        for l in english_text.split("\n")
                    )
                else:
                    est_lines = try_lines
                try_height = max(box_height, est_lines * try_size * 1.3)
                try_rect = fitz.Rect(
                    bbox[0],
                    bbox[1],
                    bbox[2],
                    bbox[1] + try_height
                )
                rc = page.insert_textbox(
                    try_rect,
                    english_text,
                    fontsize=try_size,
                    fontname=fontname,
                    color=(r, g, b),
                    align=align,
                )
                if rc >= 0:
                    break

            # 최후의 수단: insert_text로 직접 삽입
            if rc < 0:
                page.insert_text(
                    fitz.Point(bbox[0], bbox[1] + min_font),
                    english_text.replace("\n", " "),
                    fontsize=min_font,
                    fontname=fontname,
                    color=(r, g, b),
                )

        inserted += 1

    print(f"  영문 텍스트 {inserted}개 삽입 완료")


# ─── 메인 ───

def main():
    print("=" * 60)
    print("PDF 영문 변환 v2 (스마트 폰트/그룹핑)")
    print(f"입력: {PDF_PATH.name}")
    print(f"출력: {OUTPUT_PDF.name}")
    print("=" * 60)

    if not PDF_PATH.exists():
        print(f"입력 PDF 없음: {PDF_PATH}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 기존 번역 참조 데이터 로드
    existing_translations = []
    if TRANS_CACHE.exists():
        with open(TRANS_CACHE) as f:
            existing_translations = json.load(f)
        print(f"기존 번역 참조: {len(existing_translations)} 페이지")

    # Gemini 번역 캐시 로드
    gemini_cache = {}
    if GEMINI_CACHE.exists():
        with open(GEMINI_CACHE) as f:
            gemini_cache = json.load(f)
        print(f"Gemini 번역 캐시: {len(gemini_cache)} 페이지")

    # PDF 열기
    doc = fitz.open(str(PDF_PATH))
    print(f"총 {doc.page_count} 페이지\n")

    for page_num in range(doc.page_count):
        page = doc[page_num]
        process_page(doc, page_num, page, existing_translations, gemini_cache)
        time.sleep(1)  # API rate limit 방지

    # 저장
    doc.save(str(OUTPUT_PDF), garbage=4, deflate=True)
    doc.close()

    file_size = OUTPUT_PDF.stat().st_size / (1024 * 1024)
    print(f"\n{'=' * 60}")
    print(f"완료: {OUTPUT_PDF}")
    print(f"파일 크기: {file_size:.1f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
