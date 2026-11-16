"""Vision Provider Interface for PROJECT ZORO.

Provides an offline-first vision model interface for screen analysis.
Connects to local multimodal models (such as Ollama llava / minicpm-v)
or falls back to OCR + layout analysis when no local vision model is running.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

import httpx

from zoro.computer.vision.ocr import WindowsOCR

logger = logging.getLogger(__name__)


class VisionModelInterface:
    """Interface for local multimodal vision analysis."""

    def __init__(
        self,
        endpoint_url: str = "http://127.0.0.1:11434/api/generate",
        model_name: str = "llava:7b",
        ocr_engine: Optional[WindowsOCR] = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.model_name = model_name
        self.ocr_engine = ocr_engine or WindowsOCR()

    async def analyze_screen(self, image_path: Path, prompt: str) -> str:
        """Analyzes a screen image using local multimodal LLM or OCR fallback."""
        if not image_path.exists():
            return f"Error: Image {image_path} does not exist."

        # 1. Try local Ollama multimodal API
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self.endpoint_url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = data.get("response", "").strip()
                    if response_text:
                        return response_text
        except Exception as e:
            logger.debug("Local Ollama vision unavailable (%s), using OCR fallback", e)

        # 2. Offline Fallback: Windows Native OCR + geometry analysis
        ocr_res = self.ocr_engine.recognize(image_path)
        if ocr_res.success and ocr_res.full_text.strip():
            summary = [
                f"[Visual OCR Analysis: Found {len(ocr_res.words)} text elements on screen]",
                f"Visible text content:\n{ocr_res.full_text}",
            ]
            return "\n".join(summary)

        return "[Screen Analysis: Captured screen. No local multimodal model responded and no OCR text detected.]"
