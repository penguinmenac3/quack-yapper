from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget


def _paste() -> None:
    from pynput.keyboard import Controller, Key

    kb = Controller()
    with kb.pressed(Key.ctrl):
        kb.press("v")
        kb.release("v")


def insert_text(text: str, overlay: QWidget) -> None:
    QApplication.clipboard().setText(text)
    overlay.hide()
    QTimer.singleShot(80, _paste)
