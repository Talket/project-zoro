"""Local OCR Engine for PROJECT ZORO.

Uses Windows native WinRT OCR (Windows.Media.Ocr.OcrEngine) for 100% free,
offline, hardware-accelerated text extraction from screenshots and images.
Does not require external binaries, cloud APIs, or subscriptions.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union

from zoro.computer.vision.models import OCRResult, OCRWord

logger = logging.getLogger(__name__)

# Reusable PowerShell script template for WinRT OCR
_WINRT_OCR_SCRIPT_TEMPLATE = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null

$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod } | Select-Object -First 1

function AwaitTask($winRtTask, $resultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($resultType)
    $netTask = $asTask.Invoke($null, @($winRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

$imagePath = $args[0]
if (-not (Test-Path $imagePath)) {
    Write-Error "File not found: $imagePath"
    exit 1
}

$file = AwaitTask ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imagePath)) ([Windows.Storage.StorageFile])
$stream = AwaitTask ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = AwaitTask ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = AwaitTask ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$lang = [Windows.Globalization.Language]::new('en-US')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}

if ($null -eq $engine) {
    Write-Error "Could not initialize OCR engine for language"
    exit 2
}

$ocrResult = AwaitTask ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])

$words = @()
foreach ($line in $ocrResult.Lines) {
    foreach ($w in $line.Words) {
        $words += @{
            text = $w.Text
            x = $w.BoundingRect.X
            y = $w.BoundingRect.Y
            w = $w.BoundingRect.Width
            h = $w.BoundingRect.Height
        }
    }
}

$outObj = @{
    text = $ocrResult.Text
    words = $words
}

Write-Output (ConvertTo-Json $outObj -Compress)
"""


class WindowsOCR:
    """Windows native OCR engine using WinRT OcrEngine."""

    def __init__(self, script_path: Optional[Path] = None) -> None:
        if script_path is None:
            # Place helper script in cache directory or temp
            base_dir = Path.cwd() / ".zoro_cache"
            base_dir.mkdir(parents=True, exist_ok=True)
            self.script_path = base_dir / "winrt_ocr.ps1"
            if not self.script_path.exists():
                self.script_path.write_text(_WINRT_OCR_SCRIPT_TEMPLATE, encoding="utf-8")
        else:
            self.script_path = script_path

    def recognize(self, image_path: Union[str, Path], language: str = "en-US") -> OCRResult:
        """Extracts text and word bounding boxes from an image file."""
        path = Path(image_path).resolve()
        if not path.exists():
            return OCRResult(
                full_text="",
                words=[],
                language=language,
                success=False,
                error=f"Image file not found: {path}",
            )

        if os.name != "nt":
            return OCRResult(
                full_text="",
                words=[],
                language=language,
                success=False,
                error="Windows native OCR is only available on Windows NT",
            )

        try:
            # Ensure script exists
            if not self.script_path.exists():
                self.script_path.write_text(_WINRT_OCR_SCRIPT_TEMPLATE, encoding="utf-8")

            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script_path),
                str(path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                logger.warning("OCR script returned %d: %s", res.returncode, res.stderr)
                return OCRResult(
                    full_text="",
                    words=[],
                    language=language,
                    success=False,
                    error=res.stderr.strip() or f"OCR process exited with code {res.returncode}",
                )

            stdout = res.stdout.strip()
            # Extract JSON output
            data = json.loads(stdout)
            full_text = data.get("text") or ""
            raw_words = data.get("words") or []

            words: list[OCRWord] = []
            for w in raw_words:
                words.append(
                    OCRWord(
                        text=w.get("text", ""),
                        x=float(w.get("x", 0.0)),
                        y=float(w.get("y", 0.0)),
                        width=float(w.get("w", 0.0)),
                        height=float(w.get("h", 0.0)),
                    )
                )

            return OCRResult(
                full_text=full_text,
                words=words,
                language=language,
                success=True,
            )
        except Exception as e:
            logger.error("Failed to recognize image via WinRT OCR: %s", e)
            return OCRResult(
                full_text="",
                words=[],
                language=language,
                success=False,
                error=str(e),
            )
