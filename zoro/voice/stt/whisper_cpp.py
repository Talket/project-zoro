"""whisper.cpp Local Server / CLI Speech-to-Text Provider."""

from __future__ import annotations

import logging
import time
from typing import Optional
import httpx

from zoro.voice.models import STTConfig, STTResult
from zoro.voice.stt.base import BaseSTTProvider

logger = logging.getLogger(__name__)


class WhisperCppProvider(BaseSTTProvider):
    """Local Speech-to-Text adapter connecting to whisper.cpp HTTP server."""

    def __init__(self, config: Optional[STTConfig] = None, base_url: str = "http://127.0.0.1:8080") -> None:
        super().__init__(config)
        self.base_url = base_url

    @property
    def name(self) -> str:
        return "whisper.cpp"

    async def load(self) -> bool:
        self._is_loaded = await self.health_check()
        return self._is_loaded

    async def unload(self) -> None:
        self._is_loaded = False

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def transcribe(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = "en",
    ) -> STTResult:
        if not pcm_bytes:
            return STTResult(transcript="", confidence=1.0, duration_ms=0.0)

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                files = {"file": ("audio.raw", pcm_bytes, "application/octet-stream")}
                data = {
                    "language": language or self.config.language or "en",
                    "response_format": "json",
                }
                resp = await client.post(f"{self.base_url}/inference", files=files, data=data)
                if resp.status_code != 200:
                    raise RuntimeError(f"whisper.cpp server error: HTTP {resp.status_code}")

                payload = resp.json()
                text = payload.get("text", "").strip()
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return STTResult(
                    transcript=text,
                    confidence=1.0,
                    duration_ms=duration_ms,
                    language=language or "en",
                    is_final=True,
                )
        except Exception as e:
            logger.error("whisper.cpp transcription failed: %s", e)
            raise
