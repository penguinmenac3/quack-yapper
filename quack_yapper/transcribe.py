from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from quack_yapper.config import MODELS_DIR, WhisperConfig

logger = logging.getLogger(__name__)

_model_cache = None


def _get_model(config: WhisperConfig):
    global _model_cache
    if _model_cache is None:
        from faster_whisper import WhisperModel

        device = config.device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        import faster_whisper

        model_path = MODELS_DIR / config.model
        if not model_path.exists():
            logger.info("Downloading Whisper model '%s' to %s…", config.model, model_path)
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            faster_whisper.download_model(config.model, str(model_path))
            logger.info("Whisper model downloaded.")

        logger.info("Loading Whisper model '%s' on %s…", config.model, device)
        _model_cache = WhisperModel(str(model_path), device=device)
        logger.info("Whisper model loaded.")
    return _model_cache


class ModelPreloadWorker(QThread):
    def __init__(self, config: WhisperConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:
        try:
            _get_model(self._config)
        except Exception:
            logger.exception("Model preload failed")


class TranscribeWorker(QThread):
    transcription_ready = Signal(str)
    transcription_failed = Signal(str)

    def __init__(self, audio_path: Path, config: WhisperConfig, parent=None) -> None:
        super().__init__(parent)
        self._audio_path = audio_path
        self._config = config

    def run(self) -> None:
        try:
            model = _get_model(self._config)
            segments, _ = model.transcribe(str(self._audio_path), beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            self.transcription_ready.emit(text)
        except Exception as exc:
            logger.exception("Transcription failed")
            self.transcription_failed.emit(str(exc))
        finally:
            try:
                self._audio_path.unlink(missing_ok=True)
            except Exception:
                pass
