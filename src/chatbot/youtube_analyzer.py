"""
YouTube 영상 내용 추출 및 Gemini 분석 모듈
- yt-dlp로 메타데이터 + 자막 추출
- Gemini 2.5 Flash로 내용 요약/분석
- 재생목록 일괄 처리 지원
"""
from __future__ import annotations

import os
import re
import json
import logging
import subprocess
import requests
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# URL 파싱 유틸
# ─────────────────────────────────────────

def _parse_youtube_url(url: str) -> dict:
    """URL에서 video_id, playlist_id 추출"""
    video_id = None
    playlist_id = None

    # video id
    m = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', url)
    if m:
        video_id = m.group(1)

    # playlist id
    m = re.search(r'list=([A-Za-z0-9_-]+)', url)
    if m:
        playlist_id = m.group(1)

    return {'video_id': video_id, 'playlist_id': playlist_id}


# ─────────────────────────────────────────
# yt-dlp 메타데이터 + 자막 추출
# ─────────────────────────────────────────

def _get_video_meta(url: str, timeout: int = 20) -> dict:
    """yt-dlp로 영상 메타데이터 추출"""
    try:
        r = subprocess.run(
            ['python3', '-m', 'yt_dlp', '-j', '--no-download', url],
            capture_output=True, text=True, timeout=timeout
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.warning(f"yt-dlp 메타데이터 추출 실패: {e}")
    return {}


def _get_subtitle_text(meta: dict, prefer_langs: list[str] = None) -> str:
    """메타데이터에서 자막 텍스트 추출 (자동 자막 포함)"""
    if prefer_langs is None:
        prefer_langs = ['ko', 'en']

    # 자동 자막 우선
    for source_key in ['automatic_captions', 'subtitles']:
        caps = meta.get(source_key, {})
        for lang in prefer_langs:
            if lang not in caps:
                continue
            formats = caps[lang]
            # json3 포맷 우선
            fmt = next((f for f in formats if f.get('ext') == 'json3'), None)
            if not fmt:
                fmt = formats[0] if formats else None
            if not fmt or not fmt.get('url'):
                continue

            try:
                resp = requests.get(fmt['url'], timeout=10)
                if resp.status_code != 200:
                    continue

                if fmt.get('ext') == 'json3':
                    data = resp.json()
                    texts = []
                    for event in data.get('events', []):
                        for seg in event.get('segs', []):
                            t = seg.get('utf8', '').strip()
                            if t and t != '\n':
                                texts.append(t)
                    text = ' '.join(texts)
                else:
                    # vtt/srv3 등 — 줄 파싱
                    lines = []
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if line and not line.startswith('WEBVTT') and '-->' not in line and not line.isdigit():
                            # HTML 태그 제거
                            clean = re.sub(r'<[^>]+>', '', line)
                            if clean:
                                lines.append(clean)
                    text = ' '.join(lines)

                if text and len(text) > 100:
                    logger.info(f"자막 추출 성공: {lang} ({source_key}), {len(text)}자")
                    return text[:15000]  # 최대 15000자

            except Exception as e:
                logger.warning(f"자막 다운로드 실패 ({lang}): {e}")
                continue

    return ""


def _get_playlist_videos(playlist_url: str, limit: int = 50) -> list[dict]:
    """재생목록의 영상 목록 추출"""
    try:
        r = subprocess.run(
            ['python3', '-m', 'yt_dlp', '--flat-playlist',
             '--print', '%(playlist_index)s|||%(title)s|||%(url)s',
             '--playlist-end', str(limit),
             playlist_url],
            capture_output=True, text=True, timeout=30
        )
        videos = []
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                parts = line.split('|||')
                if len(parts) >= 3:
                    videos.append({
                        'index': parts[0].strip(),
                        'title': parts[1].strip(),
                        'url': parts[2].strip()
                    })
        return videos
    except Exception as e:
        logger.warning(f"재생목록 추출 실패: {e}")
        return []


# ─────────────────────────────────────────
# Gemini 분석
# ─────────────────────────────────────────

def _analyze_with_gemini(content: str, instruction: str, model: str = "gemini-2.5-flash") -> str:
    """Gemini API로 내용 분석"""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY가 설정되지 않았습니다."

    client = genai.Client(api_key=api_key)
    prompt = f"{instruction}\n\n---\n{content}"

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=2048,
            )
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini 분석 실패: {e}")
        return f"Gemini 분석 중 오류: {e}"


# ─────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────

def analyze_youtube_video(
    url: str,
    instruction: str = "이 유튜브 영상의 핵심 내용을 한국어로 요약해줘. 주요 포인트를 항목별로 정리하고, 실용적인 인사이트를 강조해줘.",
    include_transcript: bool = True,
) -> str:
    """
    유튜브 영상 URL을 받아 Gemini로 내용 분석.

    Args:
        url: YouTube 영상 URL
        instruction: 분석 지시사항 (기본: 핵심 요약)
        include_transcript: 자막 포함 여부

    Returns:
        분석 결과 문자열
    """
    logger.info(f"YouTube 분석 시작: {url}")

    # 메타데이터 추출
    meta = _get_video_meta(url)
    if not meta:
        return f"❌ 영상 정보를 가져올 수 없습니다: {url}"

    title = meta.get('title', '제목 없음')
    description = meta.get('description', '')[:2000]
    duration = meta.get('duration_string', '')
    channel = meta.get('channel', '')
    upload_date = meta.get('upload_date', '')
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    # 자막 추출
    transcript = ""
    if include_transcript:
        transcript = _get_subtitle_text(meta)

    # 분석용 컨텍스트 구성
    context_parts = [
        f"## 영상 제목\n{title}",
        f"## 채널\n{channel}",
        f"## 길이\n{duration}",
        f"## 업로드일\n{upload_date}",
    ]
    if description:
        context_parts.append(f"## 영상 설명\n{description}")
    if transcript:
        context_parts.append(f"## 자막 (전문)\n{transcript}")
    else:
        context_parts.append("## 자막\n(자막 없음 — 영상 설명 기반으로 분석)")

    context = "\n\n".join(context_parts)

    # Gemini 분석
    result = _analyze_with_gemini(context, instruction)

    header = f"🎬 **{title}**\n📺 {channel} | ⏱️ {duration} | 📅 {upload_date}\n\n"
    return header + result


def analyze_youtube_playlist(
    playlist_url: str,
    instruction: str = "이 재생목록 영상들의 핵심 내용을 한국어로 요약해줘. 각 영상별로 핵심 포인트를 1~2줄로 정리해줘.",
    limit: int = 10,
    analyze_each: bool = False,
) -> str:
    """
    재생목록의 영상들을 분석.

    Args:
        playlist_url: YouTube 재생목록 URL
        instruction: 분석 지시사항
        limit: 최대 분석할 영상 수
        analyze_each: 각 영상을 개별 분석할지 (느림) vs 제목+설명만 요약 (빠름)
    """
    videos = _get_playlist_videos(playlist_url, limit=limit)
    if not videos:
        return f"❌ 재생목록을 가져올 수 없습니다: {playlist_url}"

    if not analyze_each:
        # 빠른 모드: 제목 목록만 Gemini에 전달
        video_list = "\n".join(
            f"{v['index']}. {v['title']}" for v in videos
        )
        context = f"재생목록 영상 목록 ({len(videos)}개):\n\n{video_list}"
        result = _analyze_with_gemini(context, instruction)
        return f"📋 재생목록 분석 ({len(videos)}개 영상)\n\n" + result

    # 상세 모드: 각 영상 개별 분석 (처음 limit개만)
    results = [f"📋 재생목록 상세 분석 ({min(limit, len(videos))}개)\n"]
    for i, video in enumerate(videos[:limit]):
        results.append(f"\n---\n**{video['index']}. {video['title']}**")
        try:
            analysis = analyze_youtube_video(
                video['url'],
                instruction="이 영상의 핵심 내용을 한국어로 3줄 이내로 요약해줘.",
                include_transcript=True,
            )
            # 헤더 제거 후 요약만
            lines = analysis.split('\n')
            summary_lines = [l for l in lines[3:] if l.strip()][:5]
            results.append('\n'.join(summary_lines))
        except Exception as e:
            results.append(f"분석 실패: {e}")

    return '\n'.join(results)


def get_video_transcript(url: str) -> str:
    """자막(스크립트)만 추출"""
    meta = _get_video_meta(url)
    if not meta:
        return "영상 정보를 가져올 수 없습니다."
    title = meta.get('title', '')
    transcript = _get_subtitle_text(meta)
    if not transcript:
        return f"'{title}' 영상의 자막을 가져올 수 없습니다. (자막이 없거나 비공개 영상)"
    return f"📝 **{title}** 자막\n\n{transcript}"
