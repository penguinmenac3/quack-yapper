from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from quack_yapper.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)


class EnhanceWorker(QThread):
    enhanced = Signal(str)
    enhance_failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        text: str,
        adapter: LLMAdapter,
        system_prompt: str,
        image_bytes: bytes | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._image_bytes = image_bytes
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._adapter.cancel()

    def run(self) -> None:
        try:
            result = self._adapter.complete(self._system_prompt, self._text, self._image_bytes)
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.enhanced.emit(result)
        except Exception as exc:
            if self._cancelled:
                self.cancelled.emit()
            else:
                logger.exception("AI enhance failed")
                self.enhance_failed.emit(str(exc))
