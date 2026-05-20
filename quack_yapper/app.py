import signal
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from quack_yapper.config import load as load_config
from quack_yapper.hotkey import HotkeyBridge, HotkeyListener
from quack_yapper.overlay.window import OverlayWindow


def _make_tray_icon() -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#b4befe"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setPen(QColor("#1e1e2e"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(16)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "🦆")
    painter.end()
    return QIcon(pix)


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    config = load_config()

    overlay = OverlayWindow(config)

    bridge = HotkeyBridge()
    bridge.triggered.connect(overlay.on_hotkey)

    listener = HotkeyListener(config.hotkeys.toggle_recording, bridge)
    listener.start()

    tray = QSystemTrayIcon(_make_tray_icon(), app)
    tray.setToolTip("Quack Yapper")

    tray_menu = QMenu()
    show_action = tray_menu.addAction("Show/Hide")
    show_action.triggered.connect(overlay.show_window)
    tray_menu.addSeparator()
    exit_action = tray_menu.addAction("Exit")
    exit_action.triggered.connect(app.quit)
    tray.setContextMenu(tray_menu)

    tray.activated.connect(
        lambda reason: overlay.show_window()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    _sigint_timer = QTimer()
    _sigint_timer.start(200)
    _sigint_timer.timeout.connect(lambda: None)

    sys.exit(app.exec())
