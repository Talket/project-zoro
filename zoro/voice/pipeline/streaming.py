"""Incremental Sentence Chunking for Streaming Voice Synthesis."""

from __future__ import annotations

import re
from typing import AsyncIterator, List


class StreamingTextChunker:
    """Buffers streaming LLM tokens and yields complete sentences as soon as they form."""

    def __init__(self) -> None:
        self._buffer: str = ""
        self._sentence_delimiters = re.compile(r"([.!?]+(?:\s+|$))")

    def add_token(self, token: str) -> List[str]:
        """Append token to buffer and return any completed sentences."""
        self._buffer += token
        sentences = []

        parts = self._sentence_delimiters.split(self._buffer)
        if len(parts) > 1:
            # Everything before the last part represents completed sentences
            completed = "".join(parts[:-1]).strip()
            if completed:
                sentences.append(completed)
            self._buffer = parts[-1]

        return sentences

    def flush(self) -> str:
        """Return remaining buffered text."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining
