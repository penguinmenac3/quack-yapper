import signal
import sys

import qtawesome as qta

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from quack_yapper.config import load as load_config
from quack_yapper.hotkey import HotkeyBridge, HotkeyListener
from quack_yapper.overlay.window import OverlayWindow
from quack_yapper.transcribe import ModelPreloadWorker


def _make_tray_icon() -> QIcon:
    return qta.icon("fa5s.headset", color="white", scale_factor=0.9)


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    config = load_config()

    _preloader = ModelPreloadWorker(config.whisper)
    _preloader.start()

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
