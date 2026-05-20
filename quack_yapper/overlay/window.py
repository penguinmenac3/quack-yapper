from __future__ import annotations

import io
import logging

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QCursor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from quack_yapper import config as cfg_module
from quack_yapper import screenshot as screenshot_module
from quack_yapper.ai_enhance import EnhanceWorker
from quack_yapper.audio import AudioRecorder, device_name_to_index, list_input_devices
from quack_yapper.config import Config
from quack_yapper.insert import insert_text
from quack_yapper.llm_adapter import make_adapter
from quack_yapper.overlay.edit_view import EditView
from quack_yapper.transcribe import TranscribeWorker

logger = logging.getLogger(__name__)

_STATE_EDITING = "editing"
_STATE_RECORDING = "recording"
_STATE_TRANSCRIBING = "transcribing"
_STATE_ENHANCING = "enhancing"


class OverlayWindow(QWidget):
    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._state = _STATE_EDITING
        self._screenshot: QPixmap | None = None
        self._insert_cursor_pos: int = 0
        self._active_device: int | None = None

        self._recorder = AudioRecorder(self)
        self._recorder.amplitude_updated.connect(self._on_amplitude)

        self._transcribe_worker: TranscribeWorker | None = None
        self._enhance_worker: EnhanceWorker | None = None
        self._adapter = make_adapter(config.ai_enhance)

        self._drag_pos: QPoint | None = None

        self._build_ui()
        self._apply_window_flags()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame(self)
        self._card.setObjectName("card")
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(28)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 0)
        header_layout.addStretch()
        close_btn = QPushButton("×")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self._close_and_reset)
        header_layout.addWidget(close_btn)
        card_layout.addWidget(header)

        self._edit_view = EditView(self._card)
        self._edit_view.mic_pressed.connect(self._on_mic_pressed)
        self._edit_view.mic_select_pressed.connect(self._on_mic_select_pressed)
        self._edit_view.enhance_pressed.connect(self._on_enhance_pressed)
        self._edit_view.insert_pressed.connect(self._on_insert_pressed)
        self._edit_view.stop_pressed.connect(self._stop_recording)
        self._edit_view.cancel_enhance_pressed.connect(self._on_cancel_enhance)
        card_layout.addWidget(self._edit_view)  # cancel connected once here; not repeated in _on_enhance_pressed

        self.setFixedSize(460, 260)
        self._apply_stylesheet()
        self._resolve_initial_device()

    def _apply_window_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _apply_stylesheet(self) -> None:
        theme = self._config.ui.theme
        self.setStyleSheet(_make_stylesheet(theme))
        wave_bg, wave_bar = _WAVE_COLORS.get(theme, _WAVE_COLORS["dark"])
        self._edit_view.set_waveform_colors(wave_bg, wave_bar)

    def _center_on_cursor_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)

    def show_window(self) -> None:
        """Toggle overlay visibility without auto-starting recording (tray)."""
        if self.isVisible():
            self._close_and_reset()
        else:
            self._screenshot = screenshot_module.capture()
            self._center_on_cursor_screen()
            self.show()
            self.raise_()
            self.activateWindow()

    def on_hotkey(self) -> None:
        if not self.isVisible():
            self._screenshot = screenshot_module.capture()
            self._center_on_cursor_screen()
            self.show()
            self.raise_()
            self.activateWindow()
            self._start_recording()
        elif self._state == _STATE_EDITING:
            self._start_recording()
        elif self._state == _STATE_RECORDING:
            self._stop_recording()
        # TRANSCRIBING / ENHANCING: ignore

    def _on_mic_pressed(self) -> None:
        if self._state == _STATE_EDITING:
            self._start_recording()
        elif self._state == _STATE_RECORDING:
            self._stop_recording()

    def _start_recording(self) -> None:
        self._insert_cursor_pos = self._edit_view.cursor_pos()
        self._recorder.start(self._active_device)
        self._edit_view.set_recording()
        self._state = _STATE_RECORDING

    def _stop_recording(self) -> None:
        if self._state != _STATE_RECORDING:
            return
        wav_path = self._recorder.stop()
        self._edit_view.set_transcribing()
        self._state = _STATE_TRANSCRIBING

        worker = TranscribeWorker(wav_path, self._config.whisper, self)
        worker.transcription_ready.connect(self._on_transcription_ready)
        worker.transcription_failed.connect(self._on_transcription_failed)
        worker.finished.connect(self._on_transcribe_worker_done)
        self._transcribe_worker = worker
        worker.start()

    def _on_transcription_ready(self, text: str) -> None:
        self._state = _STATE_EDITING
        self._edit_view.insert_at(self._insert_cursor_pos, text)

    def _on_transcription_failed(self, error: str) -> None:
        logger.error("Transcription failed: %s", error)
        self._state = _STATE_EDITING
        self._edit_view.set_idle()
        self._edit_view.show_error(f"Transcription error: {error[:60]}")

    def _on_amplitude(self, rms: float) -> None:
        self._edit_view.update_amplitude(rms)

    def _on_mic_select_pressed(self) -> None:
        devices = list_input_devices()
        dialog = _MicPickerDialog(devices, self._active_device, self._config.ui.theme, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_device_change(dialog.selected_index)

    def _apply_device_change(self, sd_idx: int | None) -> None:
        self._active_device = sd_idx
        if self._state == _STATE_RECORDING:
            self._recorder.stop()
            self._recorder.start(sd_idx)
        name = ""
        if sd_idx is not None:
            name_map = {idx: n for idx, n in list_input_devices()}
            name = name_map.get(sd_idx, "")
        self._config.audio.input_device = name
        cfg_module.save(self._config)
        self._edit_view.set_device_label(name)

    def _resolve_initial_device(self) -> None:
        name = self._config.audio.input_device
        if name:
            idx = device_name_to_index(name)
            if idx is not None:
                self._active_device = idx
            else:
                logger.warning("Configured input device '%s' not found; using default.", name)
                name = ""
        self._edit_view.set_device_label(name)

    def _on_enhance_pressed(self) -> None:
        if self._state != _STATE_EDITING:
            return
        text = self._edit_view.get_text().strip()
        if not text:
            return

        dialog = _EnhanceDialog(self._screenshot, self._config.ui.theme, self)
        result = dialog.exec()

        if result == QDialog.DialogCode.Rejected:
            return

        use_screenshot = dialog.use_screenshot
        image_bytes: bytes | None = None

        if use_screenshot and self._screenshot is not None:
            image_bytes = _pixmap_to_png_bytes(self._screenshot)

        system_prompt = dialog.prompt_text
        if image_bytes is not None:
            system_prompt = system_prompt.rstrip() + "\n\n" + cfg_module.screenshot_context_sentence()

        self._edit_view.set_enhancing()
        self._state = _STATE_ENHANCING

        worker = EnhanceWorker(text, self._adapter, system_prompt, image_bytes, self)
        worker.enhanced.connect(self._on_enhanced)
        worker.enhance_failed.connect(self._on_enhance_failed)
        worker.cancelled.connect(self._on_enhance_cancelled)
        worker.finished.connect(self._on_enhance_worker_done)
        self._enhance_worker = worker
        worker.start()

    def _on_transcribe_worker_done(self) -> None:
        if self._transcribe_worker is not None:
            self._transcribe_worker.deleteLater()
            self._transcribe_worker = None

    def _on_enhance_worker_done(self) -> None:
        if self._enhance_worker is not None:
            self._enhance_worker.deleteLater()
            self._enhance_worker = None

    def _on_cancel_enhance(self) -> None:
        self._state = _STATE_EDITING
        self._edit_view.set_idle()
        if self._enhance_worker is not None:
            self._enhance_worker.cancel()

    def _on_enhanced(self, text: str) -> None:
        if self._state != _STATE_ENHANCING:
            return
        self._state = _STATE_EDITING
        self._edit_view.set_text(text)
        self._edit_view.set_idle()

    def _on_enhance_failed(self, error: str) -> None:
        if self._state != _STATE_ENHANCING:
            return
        logger.error("AI enhance failed: %s", error)
        self._state = _STATE_EDITING
        self._edit_view.set_enhancing()
        self._edit_view.show_error(f"Enhance error: {error[:60]}")

    def _on_enhance_cancelled(self) -> None:
        if self._state != _STATE_ENHANCING:
            return
        self._state = _STATE_EDITING
        self._edit_view.set_idle()

    def _on_insert_pressed(self) -> None:
        if self._state != _STATE_EDITING:
            return
        text = self._edit_view.get_text()
        if not text:
            return
        self._edit_view.clear()
        self._state = _STATE_EDITING
        insert_text(text, self)

    def _close_and_reset(self) -> None:
        if self._state == _STATE_RECORDING:
            self._recorder.stop()
        if self._state == _STATE_ENHANCING and self._enhance_worker is not None:
            self._enhance_worker.cancel()
        self._state = _STATE_EDITING
        self._edit_view.clear()
        self._screenshot = None
        self.hide()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._close_and_reset()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)


def _make_stylesheet(theme: str) -> str:
    if theme == "light":
        # Catppuccin Latte
        bg        = "#eff1f5"
        surface   = "#e6e9ef"
        border    = "#acb0be"
        text      = "#4c4f69"
        subtext   = "#6c6f85"
        muted     = "#8c8fa1"
        hover     = "#dce0e8"
        pressed   = "#ccd0da"
        selection = "#bcc0cc"
        wave_bg   = "#eff1f5"
        wave_bar  = "#7287fd"
    else:
        # Catppuccin Mocha (dark)
        bg        = "#1e1e2e"
        surface   = "#313244"
        border    = "#45475a"
        text      = "#cdd6f4"
        subtext   = "#a6adc8"
        muted     = "#6c7086"
        hover     = "#313244"
        pressed   = "#45475a"
        selection = "#585b70"
        wave_bg   = "#1e1e2e"
        wave_bar  = "#cba6f7"

    return f"""
        QWidget {{
            background: transparent;
            color: {text};
            font-family: "Segoe UI", "Inter", sans-serif;
            font-size: 13px;
        }}
        QFrame#card {{
            background-color: {bg};
            border-radius: 12px;
            border: 1px solid {border};
        }}
        QPlainTextEdit {{
            background: transparent;
            border: none;
            color: {text};
            padding: 2px 10px;
            selection-background-color: {selection};
        }}
        QFrame#separator {{
            background-color: {border};
            max-height: 1px;
            border: none;
        }}
        QPushButton {{
            background: transparent;
            border: none;
            color: {text};
            font-size: 17px;
            border-radius: 6px;
            padding: 2px 5px;
        }}
        QPushButton:hover {{
            background-color: {hover};
        }}
        QPushButton:pressed {{
            background-color: {pressed};
        }}
        QPushButton:disabled {{
            color: {border};
        }}
        QPushButton#closeBtn {{
            font-size: 16px;
            color: {muted};
            font-weight: bold;
        }}
        QPushButton#closeBtn:hover {{
            color: {text};
            background-color: {hover};
        }}
        QLabel {{
            background: transparent;
            color: {subtext};
        }}
        QPushButton#deviceBtn {{
            font-size: 11px;
            text-align: left;
            padding: 2px 8px;
            border: 1px solid {border};
            border-radius: 5px;
            color: {subtext};
        }}
        QPushButton#deviceBtn:hover {{
            border-color: {muted};
            color: {text};
            background-color: {hover};
        }}
    """


def _make_dialog_stylesheet(theme: str) -> str:
    if theme == "light":
        bg      = "#eff1f5"
        surface = "#e6e9ef"
        border  = "#acb0be"
        text    = "#4c4f69"
        hover   = "#dce0e8"
        pressed = "#ccd0da"
        sel     = "#bcc0cc"
    else:
        bg      = "#1e1e2e"
        surface = "#313244"
        border  = "#45475a"
        text    = "#cdd6f4"
        hover   = "#313244"
        pressed = "#45475a"
        sel     = "#585b70"

    return f"""
        QDialog {{
            background-color: {bg};
            color: {text};
            font-family: "Segoe UI", "Inter", sans-serif;
            font-size: 13px;
        }}
        QPlainTextEdit {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: 6px;
            color: {text};
            padding: 6px;
            selection-background-color: {sel};
        }}
        QPushButton {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: 6px;
            color: {text};
            font-size: 13px;
            padding: 5px 12px;
        }}
        QPushButton:hover {{
            background-color: {hover};
        }}
        QPushButton:pressed {{
            background-color: {pressed};
        }}
        QPushButton:disabled {{
            color: {border};
        }}
    """


_WAVE_COLORS: dict[str, tuple[str, str]] = {
    "dark":  ("#1e1e2e", "#cba6f7"),
    "light": ("#eff1f5", "#7287fd"),
}


class _MicPickerDialog(QDialog):
    def __init__(
        self,
        devices: list[tuple[int, str]],
        current: int | None,
        theme: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.selected_index: int | None = current
        self.setWindowTitle("Input device")
        self.setMinimumWidth(360)
        self.setStyleSheet(_make_dialog_stylesheet(theme))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        for sd_idx, name in [(None, "Default mic")] + [(i, n) for i, n in devices]:
            mark = "✓  " if sd_idx == current else "    "
            btn = QPushButton(f"{mark}{name}")
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda checked=False, i=sd_idx: self._pick(i))
            layout.addWidget(btn)

        layout.addSpacing(6)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _pick(self, sd_idx: int | None) -> None:
        self.selected_index = sd_idx
        self.accept()


def _pixmap_to_png_bytes(pixmap: QPixmap) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImageWriter

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buf, b"PNG")
    writer.write(pixmap.toImage())
    buf.close()
    return bytes(buf.data())


class _EnhanceDialog(QDialog):
    def __init__(
        self,
        screenshot: QPixmap | None,
        theme: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.use_screenshot = False
        self.setWindowTitle("AI Enhance")
        self.setMinimumWidth(420)
        self.setStyleSheet(_make_dialog_stylesheet(theme))

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlainText(cfg_module.enhance_prompt())
        self._prompt_edit.setFixedHeight(140)
        layout.addWidget(self._prompt_edit)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        btn_with = QPushButton("✨ With screenshot")
        btn_with.setEnabled(screenshot is not None)
        btn_with.clicked.connect(self._accept_with_screenshot)

        btn_without = QPushButton("Without")
        btn_without.setDefault(True)
        btn_without.clicked.connect(self._accept_without_screenshot)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_with)
        btn_layout.addWidget(btn_without)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    @property
    def prompt_text(self) -> str:
        return self._prompt_edit.toPlainText()

    def _accept_with_screenshot(self) -> None:
        self.use_screenshot = True
        self.accept()

    def _accept_without_screenshot(self) -> None:
        self.use_screenshot = False
        self.accept()
