from __future__ import annotations

from collections import deque

import qtawesome as qta

from PySide6.QtCore import QSize, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

_BRAILLE_FRAMES = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
_WAVEFORM_HISTORY = 60
_PAINT_HZ = 30


class WaveformWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: deque[float] = deque([0.0] * _WAVEFORM_HISTORY, maxlen=_WAVEFORM_HISTORY)
        self._bg = QColor("#1e1e2e")
        self._bar = QColor("#cba6f7")
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // _PAINT_HZ)
        self._timer.timeout.connect(self.update)
        self._timer.start()
        self.setMinimumHeight(32)

    def set_colors(self, bg: str, bar: str) -> None:
        self._bg = QColor(bg)
        self._bar = QColor(bar)
        self.update()

    def update_amplitude(self, rms: float) -> None:
        self._samples.append(rms)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        painter.fillRect(0, 0, w, h, self._bg)

        samples = list(self._samples)
        n = len(samples)
        if n == 0:
            return

        bar_w = max(1, w // n)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bar)

        for i, amp in enumerate(samples):
            bar_h = max(2, int(amp * (h - 4)))
            x = i * bar_w
            y = (h - bar_h) // 2
            painter.drawRect(x, y, max(1, bar_w - 1), bar_h)


class EditView(QWidget):
    mic_pressed = Signal()
    mic_select_pressed = Signal()
    enhance_pressed = Signal()
    insert_pressed = Signal()
    stop_pressed = Signal()
    cancel_enhance_pressed = Signal()

    def __init__(self, parent: QWidget | None = None, theme: str = "dark") -> None:
        super().__init__(parent)
        self._theme = theme
        self._spinner_idx = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("Dictate or type here…")
        self._text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._text_edit)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # Bottom bar: [device combo] [vsep] [stacked action area]
        bottom_bar = QWidget()
        bottom_bar.setFixedHeight(34)
        bar_layout = QHBoxLayout(bottom_bar)
        bar_layout.setContentsMargins(6, 0, 6, 0)
        bar_layout.setSpacing(4)

        self._btn_device = QPushButton("Default mic ▾")
        self._btn_device.setObjectName("deviceBtn")
        self._btn_device.setFixedWidth(145)
        self._btn_device.setToolTip("Change input device")
        self._btn_device.clicked.connect(self.mic_select_pressed)
        bar_layout.addWidget(self._btn_device)

        vsep = QFrame()
        vsep.setObjectName("separator")
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setFixedWidth(1)
        bar_layout.addWidget(vsep)

        self._bottom = QStackedWidget()
        bar_layout.addWidget(self._bottom, stretch=1)

        root.addWidget(bottom_bar)

        self._bottom.addWidget(self._make_toolbar())
        self._bottom.addWidget(self._make_waveform_slot())
        self._bottom.addWidget(self._make_transcribing_slot())
        self._bottom.addWidget(self._make_enhancing_slot())

        self._bottom.setCurrentIndex(0)

    def _icon(self, name: str) -> "qta.QIcon":
        color = "#cdd6f4" if self._theme == "dark" else "#4c4f69"
        return qta.icon(name, color=color)

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)

        self._btn_mic = QPushButton()
        self._btn_mic.setIcon(self._icon("fa5s.microphone"))
        self._btn_mic.setIconSize(QSize(14, 14))
        self._btn_mic.setToolTip("Record")
        self._btn_mic.setFixedSize(28, 28)
        self._btn_mic.clicked.connect(self.mic_pressed)

        self._btn_enhance = QPushButton()
        self._btn_enhance.setIcon(self._icon("fa5s.magic"))
        self._btn_enhance.setIconSize(QSize(14, 14))
        self._btn_enhance.setToolTip("AI Enhance")
        self._btn_enhance.setFixedSize(28, 28)
        self._btn_enhance.clicked.connect(self.enhance_pressed)

        self._btn_insert = QPushButton()
        self._btn_insert.setIcon(self._icon("fa5s.arrow-right"))
        self._btn_insert.setIconSize(QSize(14, 14))
        self._btn_insert.setToolTip("Insert at cursor")
        self._btn_insert.setFixedSize(28, 28)
        self._btn_insert.clicked.connect(self.insert_pressed)

        layout.addStretch()
        layout.addWidget(self._btn_mic)
        layout.addWidget(self._btn_enhance)
        layout.addWidget(self._btn_insert)
        return w

    def _make_waveform_slot(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self._waveform = WaveformWidget()
        self._waveform.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._btn_stop = QPushButton()
        self._btn_stop.setIcon(self._icon("fa5s.stop"))
        self._btn_stop.setIconSize(QSize(14, 14))
        self._btn_stop.setToolTip("Stop recording")
        self._btn_stop.setFixedSize(28, 28)
        self._btn_stop.clicked.connect(self.stop_pressed)

        layout.addWidget(self._waveform)
        layout.addWidget(self._btn_stop)
        return w

    def _make_transcribing_slot(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(6, 2, 6, 2)

        self._transcribing_label = QLabel("⣾  Transcribing…")
        self._transcribing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._transcribing_label)
        return w

    def _make_enhancing_slot(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self._enhancing_label = QLabel("⣾  Enhancing…")
        layout.addWidget(self._enhancing_label, stretch=1)

        self._btn_cancel_enhance = QPushButton()
        self._btn_cancel_enhance.setIcon(self._icon("fa5s.times"))
        self._btn_cancel_enhance.setIconSize(QSize(12, 12))
        self._btn_cancel_enhance.setToolTip("Cancel")
        self._btn_cancel_enhance.setFixedSize(24, 24)
        self._btn_cancel_enhance.clicked.connect(self.cancel_enhance_pressed)
        layout.addWidget(self._btn_cancel_enhance)
        return w

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(_BRAILLE_FRAMES)
        frame = _BRAILLE_FRAMES[self._spinner_idx]
        self._transcribing_label.setText(f"{frame}  Transcribing…")
        self._enhancing_label.setText(f"{frame}  Enhancing…")

    def set_idle(self) -> None:
        self._spinner_timer.stop()
        self._bottom.setCurrentIndex(0)
        self._text_edit.setReadOnly(False)

    def set_recording(self) -> None:
        self._spinner_timer.stop()
        self._bottom.setCurrentIndex(1)
        self._text_edit.setReadOnly(True)

    def set_transcribing(self) -> None:
        self._spinner_idx = 0
        self._transcribing_label.setText("⣾  Transcribing…")
        self._spinner_timer.start()
        self._bottom.setCurrentIndex(2)
        self._text_edit.setReadOnly(True)

    def set_enhancing(self) -> None:
        self._spinner_idx = 0
        self._enhancing_label.setText("⣾  Enhancing…")
        self._spinner_timer.start()
        self._bottom.setCurrentIndex(3)
        self._text_edit.setReadOnly(True)

    def insert_at(self, pos: int, text: str) -> None:
        cursor = self._text_edit.textCursor()
        cursor.setPosition(pos)
        if cursor.position() > 0:
            current = self._text_edit.toPlainText()
            if current and not current[cursor.position() - 1:cursor.position()].isspace():
                text = " " + text
        cursor.insertText(text)
        self._text_edit.setTextCursor(cursor)
        self.set_idle()

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def cursor_pos(self) -> int:
        return self._text_edit.textCursor().position()

    def set_device_label(self, name: str) -> None:
        if not name:
            display = "Default mic"
        else:
            display = (name[:16] + "…") if len(name) > 17 else name
        self._btn_device.setText(f"{display} ▾")

    def update_amplitude(self, rms: float) -> None:
        self._waveform.update_amplitude(rms)

    def set_waveform_colors(self, bg: str, bar: str) -> None:
        self._waveform.set_colors(bg, bar)

    def clear(self) -> None:
        self._text_edit.clear()
        self.set_idle()

    def show_error(self, message: str) -> None:
        self._enhancing_label.setText(f"⚠  {message}")
        QTimer.singleShot(3000, self.set_idle)
