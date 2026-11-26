import asyncio
import math
from functools import lru_cache
from io import BytesIO
from itertools import chain
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.core.observability import event
from app.core.security import get_principal

TRANSCRIPTION_PATH = "/api/v1/voice/transcriptions"
MAX_AUDIO_BYTES = 3 * 1024 * 1024
AUDIO_FORMATS = {"audio/webm": "matroska", "audio/ogg": "ogg", "audio/mp4": "mov"}
SAMPLE_RATE = 16000
MAX_AUDIO_SAMPLES = SAMPLE_RATE * 35

router = APIRouter()


async def recognize_groq(settings, audio: bytearray, content_type: str) -> str:
    extension = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4"}[content_type]
    try:
        async with asyncio.timeout(30):
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": "Bearer " + settings.groq_api_key},
                    files={"file": ("recording." + extension, bytes(audio), content_type)},
                    data={"model": settings.groq_transcription_model, "language": "ru", "response_format": "verbose_json"},
                )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="voice_busy")
        if response.status_code in (400, 413, 415, 422):
            raise HTTPException(status_code=422, detail="invalid_audio")
        response.raise_for_status()
        payload = response.json()
        duration = float(payload["duration"])
        text = payload["text"]
        if not math.isfinite(duration) or duration < 0 or not isinstance(text, str):
            raise ValueError("invalid_transcription")
        if duration > 35:
            raise HTTPException(status_code=413, detail="audio_too_long")
        return text.strip()
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as error:
        event("voice.failed", provider="groq", error_type=type(error).__name__)
        raise HTTPException(status_code=503, detail="voice_unavailable") from None


@lru_cache(maxsize=1)
def load_model(path: str):
    from faster_whisper import WhisperModel

    return WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)


def recognize(path: str, audio: bytearray, audio_format: str) -> str:
    import av
    import numpy as np
    from av.error import FFmpegError

    try:
        parts = []
        samples = 0
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        with av.open(BytesIO(audio), format=audio_format) as source:
            if not source.streams.audio:
                raise HTTPException(status_code=422, detail="invalid_audio")
            for frame in chain(source.decode(audio=0), (None,)):
                for converted in resampler.resample(frame):
                    samples += converted.samples
                    if samples > MAX_AUDIO_SAMPLES:
                        raise HTTPException(status_code=413, detail="audio_too_long")
                    parts.append(converted.to_ndarray().ravel())
    except FFmpegError:
        raise HTTPException(status_code=422, detail="invalid_audio") from None
    if not parts:
        return ""
    segments, _ = load_model(path).transcribe(np.concatenate(parts), language="ru", vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


@router.post(TRANSCRIPTION_PATH, tags=["voice"])
async def transcribe(request: Request, owner: str = Depends(get_principal)) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    audio_format = AUDIO_FORMATS.get(content_type)
    if audio_format is None:
        raise HTTPException(status_code=415, detail="unsupported_audio_type")

    await request.app.state.launch_limiter.check("voice:" + owner)
    settings = request.app.state.settings
    model_path = settings.whisper_model_path
    path = Path(model_path)
    if settings.voice_provider == "groq":
        if not settings.groq_api_key:
            raise HTTPException(status_code=503, detail="voice_unavailable")
    elif not model_path or not all((path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
        raise HTTPException(status_code=503, detail="voice_unavailable")

    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="request_too_large")
        audio.extend(chunk)
    if not audio:
        raise HTTPException(status_code=422, detail="empty_audio")

    lock = request.app.state.voice_lock
    if lock.locked():
        raise HTTPException(status_code=429, detail="voice_busy")
    async with lock:
        try:
            if settings.voice_provider == "groq":
                text = await recognize_groq(settings, audio, content_type)
            else:
                text = await run_in_threadpool(recognize, str(path.resolve()), audio, audio_format)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            event("voice.failed", error_type=type(error).__name__)
            raise HTTPException(status_code=503, detail="voice_unavailable") from None
    if not text:
        raise HTTPException(status_code=422, detail="speech_not_recognized")
    return {"text": text}
