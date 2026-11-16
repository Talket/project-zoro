"""Voice Latency and Performance Metrics Collector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from zoro.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class VoiceMetricsCollector:
    """Collects and stores latency telemetry for the local voice pipeline."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._recent_latencies: Dict[str, List[float]] = {
            "stt_ms": [],
            "ttft_ms": [],
            "tts_ms": [],
            "total_ms": [],
        }

    async def record_metric(self, name: str, value_ms: float, session_id: Optional[str] = None) -> None:
        """Record a single latency metric."""
        if name in self._recent_latencies:
            self._recent_latencies[name].append(value_ms)
            if len(self._recent_latencies[name]) > 100:
                self._recent_latencies[name].pop(0)

        now = datetime.now(timezone.utc)
        try:
            await self.db.execute_write(
                """
                INSERT INTO voice_metrics (session_id, metric_name, metric_value, recorded_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, name, value_ms, now.isoformat()),
            )
        except Exception as e:
            logger.debug("Failed to record metric to database: %s", e)

    def get_summary(self) -> Dict[str, float]:
        """Compute running average latencies."""
        summary = {}
        for k, v in self._recent_latencies.items():
            summary[f"avg_{k}"] = round(sum(v) / len(v), 2) if v else 0.0
        return summary
