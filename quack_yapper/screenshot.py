from __future__ import annotations

import logging

from PySide6.QtGui import QImage, QPixmap

logger = logging.getLogger(__name__)


def capture() -> QPixmap | None:
    """
    Capture the full primary screen silently using mss.
    Must be called BEFORE OverlayWindow.show() so the overlay is not in the frame.
    Returns None on Wayland or any failure.
    """
    try:
        import mss

        with mss.mss() as sct:
            monitor = sct.monitors[0]
            sct_img = sct.grab(monitor)
            w, h = sct_img.width, sct_img.height
            raw_bgra = bytes(sct_img.raw)
            image = QImage(raw_bgra, w, h, QImage.Format.Format_RGBA8888).rgbSwapped()
            return QPixmap.fromImage(image)
    except Exception as exc:
        logger.warning("Screenshot capture failed: %s", exc)
        return None
