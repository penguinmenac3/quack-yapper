from __future__ import annotations

import logging

from PySide6.QtCore import QMetaObject, QObject, Signal, Slot, Qt
from pynput import keyboard

logger = logging.getLogger(__name__)


class HotkeyBridge(QObject):
    triggered = Signal()

    @Slot()
    def _fire(self) -> None:
        self.triggered.emit()


class HotkeyListener:
    def __init__(self, combo: str, bridge: HotkeyBridge) -> None:
        self._combo = combo
        self._bridge = bridge
        self._listener: keyboard.GlobalHotKeys | None = None

    @staticmethod
    def _to_pynput_key(combo: str) -> str:
        """Convert "ctrl+shift+y" → "<ctrl>+<shift>+y"."""
        parts = combo.lower().split("+")
        formatted = []
        for part in parts:
            if len(part) == 1:
                formatted.append(part)
            else:
                formatted.append(f"<{part}>")
        return "+".join(formatted)

    def start(self) -> None:
        def _on_activate() -> None:
            QMetaObject.invokeMethod(
                self._bridge,
                "_fire",
                Qt.ConnectionType.QueuedConnection,
            )

        pynput_key = self._to_pynput_key(self._combo)
        hotkeys = {pynput_key: _on_activate}
        self._listener = keyboard.GlobalHotKeys(hotkeys)
        self._listener.daemon = True
        self._listener.start()
        logger.info("Global hotkey registered: %s", self._combo)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
