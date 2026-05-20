from __future__ import annotations

import io
import logging
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

_CHANNELS = 1
_DTYPE = "int16"
_AMPLITUDE_CEIL = 0.1


def _get_sample_rate_for_device(device: int | None) -> int:
    """Get the device's default sample rate or fall back to 48000 Hz."""
    if device is None:
        device = sd.default.device[0]
    try:
        device_info = sd.query_devices(device)
        return int(device_info["default_samplerate"])
    except Exception:
        return 48_000


_MME_SKIP = {"Microsoft Sound Mapper - Input", "Primary Sound Capture Driver"}


def list_input_devices() -> list[tuple[int, str]]:
    """Return (device_index, display_name) for real input devices.

    On Windows: uses MME device indices (support any sample rate via the
    Windows audio engine) but displays full names sourced from WASAPI.
    """
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    mme_api = next((i for i, h in enumerate(hostapis) if h["name"] == "MME"), None)
    wasapi_api = next((i for i, h in enumerate(hostapis) if h["name"] == "Windows WASAPI"), None)

    if mme_api is not None:
        mme_devs = [
            (idx, dev["name"])
            for idx, dev in enumerate(devices)
            if dev["max_input_channels"] > 0
            and dev["max_output_channels"] == 0
            and dev["hostapi"] == mme_api
            and dev["name"] not in _MME_SKIP
        ]
        if wasapi_api is not None:
            # MME truncates names; enrich with full WASAPI names via prefix match
            wasapi_names = [
                dev["name"]
                for dev in devices
                if dev["max_input_channels"] > 0
                and dev["max_output_channels"] == 0
                and dev["hostapi"] == wasapi_api
            ]
            result = []
            for idx, mme_name in mme_devs:
                full = next((w for w in wasapi_names if w.startswith(mme_name) or mme_name == w), mme_name)
                result.append((idx, full))
            return result
        return mme_devs

    # Non-Windows fallback
    return [
        (idx, dev["name"])
        for idx, dev in enumerate(devices)
        if dev["max_input_channels"] > 0 and dev["max_output_channels"] == 0
    ]


def device_name_to_index(name: str) -> int | None:
    """Return the sounddevice index for a device name, or None if not found."""
    for idx, dev_name in list_input_devices():
        if dev_name == name:
            return idx
    return None


class AudioRecorder(QObject):
    amplitude_updated = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._device: int | None = None
        self._sample_rate: int = 48_000

    def start(self, device: int | None = None) -> None:
        self._device = device
        self._frames = []
        self._sample_rate = _get_sample_rate_for_device(device)

        def _callback(indata: np.ndarray, frames: int, time, status) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)
            chunk = indata.copy()
            self._frames.append(chunk)
            float_chunk = chunk.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(float_chunk ** 2)))
            normalized = min(rms / _AMPLITUDE_CEIL, 1.0)
            self.amplitude_updated.emit(normalized)

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=_CHANNELS,
            dtype=_DTYPE,
            device=device,
            callback=_callback,
        )
        self._stream.start()
        logger.info("Recording started (device=%s, sample_rate=%s Hz)", device, self._sample_rate)

    def stop(self) -> Path:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        pcm = np.concatenate(self._frames, axis=0) if self._frames else np.zeros((0, 1), dtype=np.int16)
        self._frames = []

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(_CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm.tobytes())

        logger.info("Recording saved: %s", tmp.name)
        return Path(tmp.name)
