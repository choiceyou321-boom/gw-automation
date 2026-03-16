#!/usr/bin/env python3
"""
PDF 4~5페이지 이미지 기반 재처리 스크립트

문제: translate_pdf_inplace.py의 redact+insert_textbox 방식이
      4페이지(협회 구성원 — 증명사진+이름 라벨) 및 5페이지(출범회의 — 사진+캡션)에서
      텍스트 오버랩/겹침을 발생시킴.

해결: 해당 페이지를 고해상도 이미지로 렌더링 → Pillow로 텍스트 덮기/삽입 →
      기존 번역 PDF의 해당 페이지 교체.
"""

import os
import sys
import json
import statistics
from pathlib import Path
from functools import partial

# stdout 버퍼링 방지
print = partial(print, flush=True)

try:
    import fitz  # pymupdf
except ImportError:
    print("pymupdf 설치 필요: pip install pymupdf")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow 설치 필요: pip install Pillow")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
PDF_PATH = PROJECT_ROOT / "test 자료" / "TalkFile_대한피부건강산업협회 소개(26.03.01).pdf.pdf"
OUTPUT_DIR = PROJECT_ROOT / "data" / "kshia_translation"
OUTPUT_PDF = OUTPUT_DIR / "KSHIA_Introduction_EN.pdf"
GEMINI_CACHE = OUTPUT_DIR / "gemini_block_translations.json"

# 렌더링 DPI (고해상도)
RENDER_DPI = 300
# PDF 기본 DPI (72)
PDF_DPI = 72.0
# DPI 스케일 팩터
SCALE = RENDER_DPI / PDF_DPI

# 처리 대상 페이지 (0-indexed)
TARGET_PAGES = [3, 4]  # 4페이지, 5페이지

# ─── 폰트 탐색 ───

def find_font(bold=False):
    """시스템에서 Arial 폰트 찾기"""
    if bold:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica Bold.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
        ]

    for path in candidates:
        if os.path.exists(path):
            return path

    # 최후의 수단: 기본 폰트 사용
    return None


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


# ─── 텍스트 블록 추출 ───

def extract_text_blocks(page):
    """페이지에서 텍스트 블록을 추출하고 논리적으로 그룹화 (translate_pdf_inplace.py와 동일)"""
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
        sub_groups = []
        current_group = [lines_data[0]]

        for i in range(1, len(lines_data)):
            prev_line = current_group[-1]
            curr_line = lines_data[i]

            prev_size = prev_line["spans"][0]["size"] if prev_line["spans"] else 0
            curr_size = curr_line["spans"][0]["size"] if curr_line["spans"] else 0

            size_diff = abs(prev_size - curr_size)
            gap = curr_line["bbox"][1] - prev_line["bbox"][3]
            line_height = prev_line["bbox"][3] - prev_line["bbox"][1]

            if size_diff > 10 or gap > line_height * 2.0:
                sub_groups.append(current_group)
                current_group = [curr_line]
            else:
                current_group.append(curr_line)

        if current_group:
            sub_groups.append(current_group)

        for group in sub_groups:
            x0 = min(l["bbox"][0] for l in group)
            y0 = min(l["bbox"][1] for l in group)
            x1 = max(l["bbox"][2] for l in group)
            y1 = max(l["bbox"][3] for l in group)
            full_text = "\n".join(l["text"] for l in group)

            first_span = group[0]["spans"][0]
            avg_size = sum(l["spans"][0]["size"] for l in group) / len(group)

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


# ─── 배경색 샘플링 (Pillow 이미지 기반) ───

def sample_bg_color_pil(img, bbox_px, margin=6):
    """
    Pillow 이미지에서 텍스트 영역 주변 배경색 샘플링.
    텍스트 바로 바깥쪽 여러 지점에서 픽셀을 가져와 중앙값 사용.
    """
    x0, y0, x1, y1 = [int(v) for v in bbox_px]
    w, h = img.size

    def clamp(val, lo, hi):
        return max(lo, min(val, hi))

    # 샘플 포인트: 텍스트 영역 바깥 여백
    sample_points = [
        # 위쪽 (텍스트 위 여백)
        (clamp((x0 + x1) // 2, 0, w - 1), clamp(y0 - margin, 0, h - 1)),
        (clamp(x0 + (x1 - x0) // 4, 0, w - 1), clamp(y0 - margin, 0, h - 1)),
        (clamp(x0 + 3 * (x1 - x0) // 4, 0, w - 1), clamp(y0 - margin, 0, h - 1)),
        # 아래쪽
        (clamp((x0 + x1) // 2, 0, w - 1), clamp(y1 + margin, 0, h - 1)),
        # 좌측
        (clamp(x0 - margin, 0, w - 1), clamp((y0 + y1) // 2, 0, h - 1)),
        # 우측
        (clamp(x1 + margin, 0, w - 1), clamp((y0 + y1) // 2, 0, h - 1)),
        # 좌상/우상 대각선
        (clamp(x0 - margin, 0, w - 1), clamp(y0 - margin, 0, h - 1)),
        (clamp(x1 + margin, 0, w - 1), clamp(y0 - margin, 0, h - 1)),
    ]

    colors = []
    for sx, sy in sample_points:
        try:
            pixel = img.getpixel((sx, sy))
            if isinstance(pixel, tuple):
                colors.append(pixel[:3])
            else:
                colors.append((pixel, pixel, pixel))
        except Exception:
            continue

    if not colors:
        return (255, 255, 255)  # 기본 흰색

    # 사진 픽셀(어두운 색)을 필터링 — 밝기 기준으로 밝은 쪽 선택
    bright_colors = [c for c in colors if sum(c) > 300]  # 밝기 합 > 300 (밝은 배경)
    if bright_colors and len(bright_colors) >= 3:
        colors = bright_colors

    # 중앙값 사용
    colors.sort(key=lambda c: sum(c))
    mid = len(colors) // 2
    return colors[mid]


# ─── 폰트 크기 자동 계산 ───

def fit_text_in_box(draw, text, bbox_px, font_path, bold_font_path, is_bold,
                    original_size_pt, min_size=8):
    """
    텍스트가 bbox에 맞도록 폰트 크기를 자동 계산.
    반환: (font, fitted_lines, font_size_px)
    """
    x0, y0, x1, y1 = bbox_px
    box_w = x1 - x0
    box_h = y1 - y0

    # 원본 폰트 크기를 픽셀로 변환
    original_size_px = original_size_pt * SCALE

    # 사용할 폰트 경로
    fp = bold_font_path if is_bold and bold_font_path else font_path

    # 원본 크기에서 시작하여 줄여나감
    for size_px in range(int(original_size_px), int(min_size * SCALE) - 1, -1):
        if size_px < min_size * SCALE * 0.8:
            break

        try:
            if fp:
                font = ImageFont.truetype(fp, size_px)
            else:
                font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        # 텍스트를 줄 단위로 나누되, 원본 \n 유지 + 자동 줄바꿈
        lines = []
        for paragraph in text.split("\n"):
            wrapped = wrap_text_to_width(draw, paragraph, font, box_w)
            lines.extend(wrapped)

        # 높이 계산
        line_height = size_px * 1.2
        total_height = line_height * len(lines)

        if total_height <= box_h * 1.15:  # 약간의 여유 (15%)
            return font, lines, size_px

    # 최소 크기로 강제 적용
    min_px = max(int(min_size * SCALE), 8)
    try:
        if fp:
            font = ImageFont.truetype(fp, min_px)
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    lines = []
    for paragraph in text.split("\n"):
        wrapped = wrap_text_to_width(draw, paragraph, font, box_w)
        lines.extend(wrapped)

    return font, lines, min_px


def wrap_text_to_width(draw, text, font, max_width):
    """텍스트를 max_width에 맞게 줄바꿈"""
    if not text.strip():
        return [""]

    words = text.split(" ")
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            # 단어 자체가 너무 길면 그냥 넣기
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [""]


# ─── 페이지 이미지 기반 처리 ───

def process_page_image_based(orig_doc, page_num, translations, font_path, bold_font_path):
    """
    원본 PDF 페이지를 이미지로 렌더링 → 텍스트 영역 덮기 → 영문 삽입.
    반환: Pillow Image 객체
    """
    page = orig_doc[page_num]
    print(f"\n--- 페이지 {page_num + 1} (이미지 기반 처리) ---")

    # 1. 고해상도 렌더링
    pixmap = page.get_pixmap(dpi=RENDER_DPI)
    img_data = pixmap.tobytes("png")

    import io
    img = Image.open(io.BytesIO(img_data)).convert("RGB")
    draw = ImageDraw.Draw(img)

    print(f"  이미지 크기: {img.size[0]}x{img.size[1]} px (DPI={RENDER_DPI})")

    # 2. 텍스트 블록 추출
    text_blocks = extract_text_blocks(page)
    kr_blocks = [(i, b) for i, b in enumerate(text_blocks) if b["needs_translation"]]
    print(f"  전체 블록: {len(text_blocks)}, 번역 필요: {len(kr_blocks)}")

    # 3. 번역 매핑 가져오기
    cache_key = str(page_num)
    if cache_key not in translations:
        print(f"  번역 데이터 없음 — 건너뜀")
        return img

    mapping = {int(k): v for k, v in translations[cache_key].items()}
    print(f"  번역 매핑: {len(mapping)}개")

    # 4. 각 한글 블록 처리: 배경으로 덮고 영문 삽입
    processed = 0
    skipped = 0

    for block_idx, block in kr_blocks:
        if block_idx not in mapping:
            skipped += 1
            continue

        english_text = mapping[block_idx].strip()
        if not english_text:
            skipped += 1
            continue

        # PDF 좌표 → 이미지 픽셀 좌표
        bbox = block["bbox"]
        bbox_px = [
            int(bbox[0] * SCALE),
            int(bbox[1] * SCALE),
            int(bbox[2] * SCALE),
            int(bbox[3] * SCALE),
        ]

        # 라인 단위로 배경 덮기 (더 정확한 배경색 샘플링)
        for line_info in block["lines"]:
            line_bbox = line_info["bbox"]
            line_bbox_px = [
                int(line_bbox[0] * SCALE),
                int(line_bbox[1] * SCALE),
                int(line_bbox[2] * SCALE),
                int(line_bbox[3] * SCALE),
            ]

            # 배경색 샘플링
            bg_color = sample_bg_color_pil(img, line_bbox_px, margin=int(8 * SCALE / 4))

            # 패딩 추가하여 잔여 텍스트 제거
            pad_x = int(3 * SCALE)
            pad_y = int(2 * SCALE)
            cover_rect = [
                max(0, line_bbox_px[0] - pad_x),
                max(0, line_bbox_px[1] - pad_y),
                min(img.size[0], line_bbox_px[2] + pad_x),
                min(img.size[1], line_bbox_px[3] + pad_y),
            ]

            draw.rectangle(cover_rect, fill=bg_color)

        # 텍스트 색상 변환
        color_int = block["color"]
        text_color = (
            (color_int >> 16) & 0xFF,
            (color_int >> 8) & 0xFF,
            color_int & 0xFF,
        )

        # 폰트 크기 자동 계산 및 텍스트 맞추기
        font, fitted_lines, font_size_px = fit_text_in_box(
            draw, english_text, bbox_px,
            font_path, bold_font_path,
            block["is_bold"],
            block["font_size"],
            min_size=8,
        )

        # 텍스트 그리기
        line_height = font_size_px * 1.2
        # 수직 시작 위치: bbox 상단에서 시작
        y_start = bbox_px[1]

        for i, line in enumerate(fitted_lines):
            y_pos = y_start + i * line_height

            # bbox 하단을 넘으면 중단 (오버랩 방지)
            if y_pos + font_size_px > bbox_px[3] + font_size_px * 0.5:
                # 남은 텍스트가 있으면 마지막 줄에 축약
                if i < len(fitted_lines) - 1:
                    remaining = " ".join(fitted_lines[i:])
                    # 축약 가능하면 ... 붙이기
                    truncated = remaining[:int((bbox_px[2] - bbox_px[0]) / (font_size_px * 0.5))]
                    if len(truncated) < len(remaining):
                        truncated = truncated.rstrip() + "..."
                    draw.text((bbox_px[0], y_pos), truncated, fill=text_color, font=font)
                break

            draw.text((bbox_px[0], y_pos), line, fill=text_color, font=font)

        processed += 1

    print(f"  처리: {processed}개, 건너뜀: {skipped}개")
    return img


# ─── 메인: 기존 PDF의 4~5페이지 교체 ───

def main():
    print("=" * 60)
    print("PDF 4~5페이지 이미지 기반 재처리")
    print(f"원본 PDF: {PDF_PATH.name}")
    print(f"대상 PDF: {OUTPUT_PDF.name}")
    print(f"처리 페이지: {[p + 1 for p in TARGET_PAGES]}")
    print("=" * 60)

    # 파일 존재 확인
    if not PDF_PATH.exists():
        print(f"원본 PDF 없음: {PDF_PATH}")
        sys.exit(1)

    if not OUTPUT_PDF.exists():
        print(f"번역 PDF 없음: {OUTPUT_PDF}")
        sys.exit(1)

    # 번역 캐시 로드
    if not GEMINI_CACHE.exists():
        print(f"번역 캐시 없음: {GEMINI_CACHE}")
        sys.exit(1)

    with open(GEMINI_CACHE) as f:
        translations = json.load(f)
    print(f"번역 캐시 로드: {len(translations)} 페이지")

    # 폰트 찾기
    font_path = find_font(bold=False)
    bold_font_path = find_font(bold=True)
    print(f"일반 폰트: {font_path}")
    print(f"볼드 폰트: {bold_font_path}")

    # 원본 PDF 열기 (텍스트 블록 추출 + 이미지 렌더링용)
    orig_doc = fitz.open(str(PDF_PATH))

    # 각 대상 페이지를 이미지로 처리
    page_images = {}
    for page_num in TARGET_PAGES:
        img = process_page_image_based(
            orig_doc, page_num, translations, font_path, bold_font_path
        )
        page_images[page_num] = img

    orig_doc.close()

    # 번역 PDF 열기 → 해당 페이지 교체
    print(f"\n--- 번역 PDF 페이지 교체 ---")
    out_doc = fitz.open(str(OUTPUT_PDF))

    for page_num, img in page_images.items():
        print(f"  페이지 {page_num + 1} 교체 중...")

        # Pillow 이미지 → PNG 바이트
        import io
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG", optimize=True)
        img_bytes = img_bytes.getvalue()

        # 기존 페이지의 크기 가져오기
        old_page = out_doc[page_num]
        page_rect = old_page.rect

        # 기존 페이지 삭제 후 빈 페이지 삽입
        out_doc.delete_page(page_num)
        out_doc.new_page(pno=page_num, width=page_rect.width, height=page_rect.height)

        # 새 페이지에 이미지 삽입
        new_page = out_doc[page_num]
        new_page.insert_image(page_rect, stream=img_bytes)

        print(f"  페이지 {page_num + 1} 교체 완료")

    # 저장
    # 임시 파일에 먼저 저장 후 교체 (안전)
    temp_pdf = OUTPUT_PDF.with_suffix(".tmp.pdf")
    out_doc.save(str(temp_pdf), garbage=4, deflate=True)
    out_doc.close()

    # 백업 후 교체
    backup_pdf = OUTPUT_PDF.with_suffix(".backup.pdf")
    if backup_pdf.exists():
        backup_pdf.unlink()
    OUTPUT_PDF.rename(backup_pdf)
    temp_pdf.rename(OUTPUT_PDF)

    file_size = OUTPUT_PDF.stat().st_size / (1024 * 1024)
    print(f"\n{'=' * 60}")
    print(f"완료: {OUTPUT_PDF}")
    print(f"파일 크기: {file_size:.1f} MB")
    print(f"백업: {backup_pdf}")
    print("=" * 60)


if __name__ == "__main__":
    main()
