"""
Google Cloud Speech-to-Text API 래퍼 모듈

음성 파일을 텍스트로 변환합니다.
- 지원 형식: MP3, WAV, M4A, OGG, FLAC, WebM
- 한국어(ko-KR) 기본, 영어(en-US) 자동 감지
- 짧은 오디오(≤1분): 동기 처리
- 긴 오디오(>1분): 비동기 처리 (GCS 업로드 필요)
"""

import os
import subprocess
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 서비스 계정 키 경로
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_CREDENTIALS_PATH = _PROJECT_ROOT / "config" / "google_service_account.json"

# 지원하는 오디오 MIME 타입
AUDIO_MIME_TYPES = {
    "audio/mpeg",        # MP3
    "audio/mp3",         # MP3 (비표준)
    "audio/wav",         # WAV
    "audio/x-wav",       # WAV (비표준)
    "audio/mp4",         # M4A
    "audio/x-m4a",       # M4A (비표준)
    "audio/m4a",         # M4A (비표준)
    "audio/ogg",         # OGG (Opus/Vorbis)
    "audio/flac",        # FLAC
    "audio/webm",        # WebM
    "audio/x-flac",      # FLAC (비표준)
}

# 파일 확장자 → Speech-to-Text 인코딩 매핑
_ENCODING_MAP = {
    ".wav": "LINEAR16",
    ".flac": "FLAC",
    ".ogg": "OGG_OPUS",
    ".mp3": "MP3",
    ".m4a": None,       # ffmpeg로 WAV 변환 필요
    ".webm": None,      # ffmpeg로 WAV 변환 필요
    ".mp4": None,       # ffmpeg로 WAV 변환 필요
}


def is_audio_file(mime_type: str) -> bool:
    """MIME 타입이 지원하는 오디오인지 확인"""
    return mime_type in AUDIO_MIME_TYPES


def _get_audio_duration(file_path: str) -> float:
    """ffprobe로 오디오 길이(초) 반환"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"오디오 길이 측정 실패: {e}")
        return 0.0


def _convert_to_wav(input_path: str) -> str:
    """ffmpeg로 오디오를 16kHz mono WAV로 변환"""
    tmp_dir = str(_PROJECT_ROOT / "data" / "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    fd, output_path = tempfile.mkstemp(suffix=".wav", dir=tmp_dir)
    os.close(fd)  # ffmpeg가 직접 쓸 수 있도록 fd 닫기

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-ar", "16000",        # 샘플레이트 16kHz
                "-ac", "1",            # 모노
                "-sample_fmt", "s16",  # 16bit PCM
                output_path,
            ],
            capture_output=True, text=True, timeout=120,
            check=True,
        )
        logger.info(f"오디오 변환 완료: {input_path} → {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg 변환 실패: {e.stderr}")
        raise RuntimeError(f"오디오 변환 실패: {e.stderr[:200]}")


_speech_client = None


def _get_client():
    """Speech-to-Text 클라이언트 싱글톤 (서비스 계정 인증)"""
    global _speech_client
    if _speech_client is not None:
        return _speech_client

    from google.cloud import speech

    if _CREDENTIALS_PATH.exists():
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(_CREDENTIALS_PATH))
    elif not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError(
            "Google 서비스 계정 키가 없습니다. "
            "config/google_service_account.json을 생성해주세요."
        )

    _speech_client = speech.SpeechClient()
    return _speech_client


def transcribe_audio(file_path: str, language: str = "ko-KR") -> dict:
    """
    음성 파일을 텍스트로 변환

    Args:
        file_path: 오디오 파일 경로
        language: 언어 코드 (기본: ko-KR)

    Returns:
        {
            "text": "변환된 텍스트",
            "duration_seconds": 123.4,
            "language": "ko-KR",
            "confidence": 0.95,
            "success": True
        }
    """
    from google.cloud import speech

    file_path = str(file_path)
    ext = Path(file_path).suffix.lower()

    # 오디오 길이 측정
    duration = _get_audio_duration(file_path)
    logger.info(f"음성 파일: {Path(file_path).name} ({duration:.1f}초, {ext})")

    # 변환이 필요한 형식인지 확인
    encoding = _ENCODING_MAP.get(ext)
    wav_path = None

    if encoding is None:
        # WAV로 변환 필요
        logger.info(f"{ext} → WAV 변환 중...")
        wav_path = _convert_to_wav(file_path)
        file_path = wav_path
        encoding = "LINEAR16"
        ext = ".wav"

    try:
        client = _get_client()

        # 오디오 파일 읽기
        with open(file_path, "rb") as f:
            audio_data = f.read()

        audio = speech.RecognitionAudio(content=audio_data)

        # 인코딩 설정
        encoding_enum = getattr(speech.RecognitionConfig.AudioEncoding, encoding)

        config = speech.RecognitionConfig(
            encoding=encoding_enum,
            sample_rate_hertz=16000 if encoding == "LINEAR16" else None,
            language_code=language,
            alternative_language_codes=["en-US"] if language == "ko-KR" else [],
            enable_automatic_punctuation=True,
            model="latest_long" if duration > 60 else "latest_short",
        )

        # 동기/비동기 분기
        if duration <= 60:
            # 동기 처리 (≤1분)
            logger.info("동기 STT 처리 중...")
            response = client.recognize(config=config, audio=audio)
        else:
            # 긴 오디오: 로컬 파일로 비동기 처리 (60초 이상)
            # NOTE: 로컬 파일 기반 비동기는 content 크기 제한(~10MB)이 있음
            # 매우 긴 파일은 GCS 업로드 필요 (추후 구현)
            logger.info(f"비동기 STT 처리 중 ({duration:.0f}초)...")
            operation = client.long_running_recognize(config=config, audio=audio)
            response = operation.result(timeout=300)

        # 결과 추출
        texts = []
        total_confidence = 0
        count = 0

        for result in response.results:
            alt = result.alternatives[0]
            texts.append(alt.transcript)
            total_confidence += alt.confidence
            count += 1

        full_text = " ".join(texts)
        avg_confidence = total_confidence / count if count > 0 else 0

        logger.info(f"STT 완료: {len(full_text)}자, 신뢰도 {avg_confidence:.2%}")

        return {
            "text": full_text,
            "duration_seconds": round(duration, 1),
            "language": language,
            "confidence": round(avg_confidence, 4),
            "success": True,
        }

    except Exception as e:
        logger.error(f"STT 실패: {e}")
        return {
            "text": "",
            "duration_seconds": round(duration, 1),
            "language": language,
            "confidence": 0,
            "success": False,
            "error": str(e),
        }

    finally:
        # 임시 WAV 파일 정리
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
