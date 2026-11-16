"""Screen Capture & Computer Perception for PROJECT ZORO."""

from zoro.computer.vision.capture import ScreenCaptureManager
from zoro.computer.vision.models import CaptureResult, OCRResult, OCRWord, ScreenRegion
from zoro.computer.vision.ocr import WindowsOCR
from zoro.computer.vision.vision_provider import VisionModelInterface

__all__ = [
    "CaptureResult",
    "OCRResult",
    "OCRWord",
    "ScreenCaptureManager",
    "ScreenRegion",
    "VisionModelInterface",
    "WindowsOCR",
]
