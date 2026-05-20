# Quack Yapper — Component Specs

Detailed interface and responsibility notes for each module. Read alongside [README.md](README.md).

---

## `config.py`

**Responsibilities:** load `config.toml`, write defaults on first run, expose a typed `Config` object, locate prompt files.

```python
@dataclass
class WhisperConfig:
    model: str = "base"      # tiny | base | small | medium | large
    device: str = "auto"     # auto | cpu | cuda

@dataclass
class AIConfig:
    provider: str = "openai"   # "openai" | "bedrock"
    model: str = "llama3.2"
    base_url: str = "http://localhost:11434/v1"   # OpenAI: /v1 endpoint; Bedrock: endpoint URL
    api_key: str = ""
    region: str = "us-east-1"                     # Bedrock only; ignored for OpenAI

@dataclass
class HotkeyConfig:
    toggle_recording: str = "ctrl+shift+y"

@dataclass
class Config:
    hotkeys: HotkeyConfig
    whisper: WhisperConfig
    ai_enhance: AIConfig

CONFIG_DIR = Path.home() / ".config" / "quack-yapper"

def load() -> Config: ...          # creates CONFIG_DIR and defaults if missing
def enhance_prompt() -> str: ...   # reads enhance-prompt.md; returns built-in default + warning if missing
```

**Prompt fallback:** if the file is missing, `logging.warning(f"Prompt file not found: {path}. Using built-in default.")` and return an embedded default string. Never raise — the app must remain usable.

---

## `hotkey.py`

**Responsibilities:** register a global hotkey via `pynput`; bridge the pynput thread to Qt via a `QObject` signal.

```python
class HotkeyBridge(QObject):
    triggered = Signal()

class HotkeyListener:
    def __init__(self, combo: str, bridge: HotkeyBridge): ...
    def start(self) -> None: ...   # starts pynput.GlobalHotKeys in daemon thread
    def stop(self) -> None: ...
```

**Thread bridge:** pynput callbacks run in a foreign thread. Emit `bridge.triggered` via `QMetaObject.invokeMethod(bridge, "triggered", Qt.QueuedConnection)` to safely cross the thread boundary into the Qt main thread.

---

## `screenshot.py`

**Responsibilities:** capture the full screen silently; return a `QPixmap`; never block the UI thread.

```python
def capture() -> QPixmap | None:
    """
    Cross-platform via mss: mss.mss().grab(monitor) → BGRA bytes → QImage → QPixmap.
    Works on Windows and Linux X11. Returns None on Wayland or any other failure.
    Must be called BEFORE OverlayWindow.show() so the overlay is not in the frame.
    """
```

**Conversion:** `mss` returns a raw BGRA buffer. Build `QImage(bytes(sct_img.rgb), w, h, QImage.Format.Format_RGB888)` (or `Format_RGBA8888` from the BGRA buffer with channel swap) then `QPixmap.fromImage()`.

**Timing:** called synchronously in `OverlayWindow` at hotkey-press time, before `self.show()`. The call is fast (<50 ms on most hardware) so no thread is needed, but wrap in a try/except and return `None` on any failure.

---

## `audio.py`

**Responsibilities:** open a `sounddevice.InputStream`; accumulate PCM frames; emit amplitude for UI; flush to a temp WAV file on stop.

```python
class AudioRecorder(QObject):
    amplitude_updated = Signal(float)   # RMS in [0.0, 1.0]; ~30 Hz

    def start(self, device: int | None = None) -> None:
        """Opens InputStream on device index (None → system default)."""
    def stop(self) -> Path:
        """Stops stream, writes PCM to NamedTemporaryFile(.wav), returns path."""

def list_input_devices() -> list[tuple[int, str]]:
    """Returns [(index, name), ...] for all input-capable devices.
    Uses sounddevice.query_devices(); filters to hostapi devices with max_input_channels > 0.
    """
```

**Device switching mid-recording:** if `device_changed` fires while recording is active, `OverlayWindow` calls `recorder.stop()` (discards the buffer), then `recorder.start(new_device)` immediately. The user effectively restarts the take on the new mic.

**Amplitude:** compute `np.sqrt(np.mean(frames**2))` (RMS) per callback chunk; normalize to `[0, 1]` with a reasonable ceiling (e.g. `0.1` full-scale RMS → 1.0). Emit via `QMetaObject.invokeMethod` from the sounddevice callback thread.

**WAV format:** 16-bit PCM, 16 000 Hz mono — matches faster-whisper's preferred input; avoids resampling overhead.

---

## `transcribe.py`

**Responsibilities:** run faster-whisper in a `QThread`; cache the `WhisperModel` singleton; emit result or error.

```python
_model_cache: WhisperModel | None = None  # module-level singleton

class TranscribeWorker(QThread):
    transcription_ready = Signal(str)
    transcription_failed = Signal(str)

    def __init__(self, audio_path: Path, config: WhisperConfig): ...
    def run(self) -> None: ...   # loads model if not cached, runs transcribe(), emits signal
```

**Model caching:** the first call to `WhisperModel(size, device=device)` may take 1–3 s. Cache it at the module level. Subsequent calls reuse the in-memory model with no reload cost.

**Cleanup:** delete the temp WAV file in `run()` after transcription is complete (successful or not).

---

## `llm_adapter.py`

**Responsibilities:** thin, fully synchronous LLM abstraction. `complete()` blocks the calling `QThread` until the response arrives. No asyncio, no streaming, no thread bridges.

```python
class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_text: str, image_bytes: bytes | None = None) -> str:
        """Blocking. Safe to call from a QThread; never call from the main thread."""
        ...
    def cancel(self) -> None:
        """Close the underlying connection. Called from the main thread while complete() blocks.
        Causes complete() to raise, which EnhanceWorker catches silently."""
        ...

class OpenAIAdapter(LLMAdapter):
    """httpx.post to any OpenAI-compatible /chat/completions endpoint."""
    def __init__(self, base_url: str, api_key: str, model: str) -> None: ...
    def complete(self, ...) -> str: ...
    def cancel(self) -> None:
        """Closes the shared httpx.Client, causing the in-flight post() to raise."""
        self._client.close()

class BedrockAdapter(LLMAdapter):
    """boto3 client.converse() — non-streaming Bedrock Converse API.
    api_key is written to os.environ["AWS_BEARER_TOKEN_BEDROCK"] on init.
    """
    def __init__(self, base_url: str, region: str, api_key: str, model: str) -> None: ...
    def complete(self, ...) -> str: ...
    def cancel(self) -> None:
        """Best-effort: closes the botocore HTTP session to interrupt the blocking call."""
        try:
            self._client._endpoint.http_session.close()
        except Exception:
            pass

def make_adapter(config: AIConfig) -> LLMAdapter:
    """Factory: reads config.provider and returns the correct adapter instance."""
    ...
```

**Timeout:** 5 minutes read, 10 s connect. If the model doesn't respond in 5 minutes the user wouldn't wait anyway; on timeout `EnhanceWorker` catches the exception, emits `enhance_failed`, and `OverlayWindow` calls `set_idle()` keeping the original text.

**`OpenAIAdapter.complete`:**

```python
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0)

# Text-only
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_text},
]

# With image (OpenAI vision — base64 data URL)
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]},
]

resp = httpx.post(
    f"{base_url}/chat/completions",
    json={"model": model, "messages": messages},
    headers={"Authorization": f"Bearer {api_key or 'unused'}"},
    timeout=_TIMEOUT,
)
resp.raise_for_status()
return resp.json()["choices"][0]["message"]["content"]
```

**`BedrockAdapter.complete`:**

```python
from botocore.config import Config

_CLIENT = boto3.client(
    "bedrock-runtime",
    endpoint_url=base_url,
    region_name=region,
    config=Config(connect_timeout=10, read_timeout=300),
)

# System is a top-level key; content is a list of blocks
resp = _CLIENT.converse(
    modelId=model,
    system=[{"text": system_prompt}],
    messages=[{"role": "user", "content": content}],
    # content = [{"text": user_text}]
    # or      = [{"text": user_text}, {"image": {"format": "png", "source": {"bytes": image_bytes}}}]
)
return resp["output"]["message"]["content"][0]["text"]
```

Note: Bedrock `converse()` takes raw bytes for images — no base64 encoding needed.

**Image encoding:** `OverlayWindow` converts `QPixmap` → raw PNG `bytes` once (`QBuffer` + `QImageWriter("png")`); `OpenAIAdapter` base64-encodes them; `BedrockAdapter` passes them as-is.

---

## `ai_enhance.py`

**Responsibilities:** run `LLMAdapter.complete()` in a `QThread`; emit result, error, or cancellation.

```python
class EnhanceWorker(QThread):
    enhanced = Signal(str)
    enhance_failed = Signal(str)
    cancelled = Signal()            # emitted instead of enhance_failed when cancel() was called

    def __init__(
        self,
        text: str,
        adapter: LLMAdapter,
        system_prompt: str,
        image_bytes: bytes | None = None,
    ): ...

    def cancel(self) -> None:
        """Called from the main thread. Sets flag then delegates to adapter."""
        self._cancelled = True
        self._adapter.cancel()

    def run(self) -> None:
        try:
            result = self._adapter.complete(self._system_prompt, self._text, self._image_bytes)
            self.enhanced.emit(result)
        except Exception as exc:
            if self._cancelled:
                self.cancelled.emit()   # silent — OverlayWindow just calls set_idle()
            else:
                self.enhance_failed.emit(str(exc))
```

`OverlayWindow` connects `[✕]` in the enhancing slot to `worker.cancel()`. Both `cancelled` and `enhanced` lead to `edit_view.set_idle()`; `enhance_failed` additionally shows a brief error message in the bottom zone before resetting.

`OverlayWindow` constructs the adapter once at startup via `make_adapter(config.ai_enhance)` and reuses it across calls.

---

## `insert.py`

**Responsibilities:** write text to clipboard; hide the overlay (OS returns focus automatically); simulate Ctrl+V via pynput.

```python
def insert_text(text: str) -> None:
    """
    No window-ID bookkeeping needed.
    When the overlay hides the OS naturally returns focus to the previous window.
    pynput then fires Ctrl+V into that window.
    """
```

**Implementation:**

```python
from pynput.keyboard import Controller, Key

def _paste() -> None:
    kb = Controller()
    with kb.pressed(Key.ctrl):
        kb.press('v')
        kb.release('v')

def insert_text(text: str, overlay: QWidget) -> None:
    QApplication.clipboard().setText(text)
    overlay.hide()
    # 80 ms: enough for the WM to complete the focus handoff on both Windows and X11
    QTimer.singleShot(80, _paste)
```

**Why this works:** `overlay.hide()` causes the OS window manager to immediately restore focus to the previously active window. The 80 ms `singleShot` fires after Qt has processed the hide event and the WM has completed the focus switch; `pynput` then delivers Ctrl+V to whatever window owns focus — which is the original app.

No `pywin32`, no `xdotool`, no stored window IDs. Fully cross-platform.

---

## `overlay/window.py`

**Responsibilities:** frameless always-on-top shell; hosts `EditView`; wires hotkey and workers.

```python
class OverlayWindow(QWidget):
    _edit_view: EditView
    _recorder: AudioRecorder
    _screenshot: QPixmap | None
    _insert_cursor_pos: int | None   # saved when mic starts, used on transcription_ready
```

**Window flags:**

```python
self.setWindowFlags(
    Qt.FramelessWindowHint
    | Qt.WindowStaysOnTopHint
    | Qt.Tool           # no taskbar entry
)
self.setAttribute(Qt.WA_TranslucentBackground)
```

**Positioning:** center on the screen that contains the cursor (`QGuiApplication.screenAt(QCursor.pos())`).

**Hotkey handling (`_on_hotkey`):**

| Window state | Action |
|---|---|
| Hidden | Capture screenshot, show window, call `_start_recording()` |
| Visible + EDITING | Call `_start_recording()` (saves cursor pos) |
| Visible + RECORDING | Call `_stop_recording()` |
| Visible + TRANSCRIBING | Ignore |

**`_start_recording()`:** saves `edit_view.cursor_pos()` to `_insert_cursor_pos`, calls `recorder.start(device)`, calls `edit_view.set_recording(True)`.

**`_stop_recording()`:** calls `recorder.stop()` → WAV path, calls `edit_view.set_transcribing()`, starts `TranscribeWorker`.

**On `transcription_ready(text)`:** calls `edit_view.insert_at(_insert_cursor_pos, text)`, which also calls `edit_view.set_idle()`.

---

## `overlay/edit_view.py`

**Responsibilities:** single persistent view; text box + inline status strip + three-button toolbar.

```python
class WaveformWidget(QWidget):
    def update_amplitude(self, rms: float) -> None: ...
    def paintEvent(self, event) -> None: ...

class EditView(QWidget):
    mic_pressed = Signal()           # left-click on mic button
    mic_right_clicked = Signal()     # right-click → OverlayWindow opens device QMenu
    enhance_pressed = Signal()       # opens screenshot QDialog in OverlayWindow
    insert_pressed = Signal()

    # Visual state setters called by OverlayWindow
    def set_idle(self) -> None: ...          # slot 0 (toolbar), text box re-enabled
    def set_recording(self) -> None: ...     # slot 1 (waveform), text box read-only
    def set_transcribing(self) -> None: ...  # slot 2 ("Transcribing…"), text box read-only
    def set_enhancing(self) -> None: ...     # slot 3 ("⣷ Enhancing…"), text box read-only

    def insert_at(self, pos: int, text: str) -> None: ...
    def get_text(self) -> str: ...
    def cursor_pos(self) -> int: ...
    def update_amplitude(self, rms: float) -> None: ...
```

**Layout (top → bottom):**

1. `QPlainTextEdit` — fills available space
2. **Bottom zone** (`QStackedWidget`, fixed height, always visible):
   - Slot 0 — **Toolbar**: `[🎤 mic]` `[✨ enhance]` `[➜ insert]` icon-only `QPushButton`s
   - Slot 1 — **Waveform**: `WaveformWidget` + `[⏹]` stop button on the right
   - Slot 2 — **Transcribing**: `QLabel` with animated braille spinner + "Transcribing…"
   - Slot 3 — **Enhancing**: braille spinner label + `[✕]` cancel `QPushButton` on the right

The active slot changes with each state call (`set_idle` → 0, `set_recording` → 1, `set_transcribing` → 2, `set_enhancing` → 3). The window height never changes. `QPlainTextEdit.setReadOnly(True/False)` is toggled in each setter.

**Waveform painting:** `deque[float]` of last N RMS samples; `paintEvent` draws a scrolling bar chart via `QPainter`. Timer at 30 Hz calls `update()` to repaint.

**AI Enhance flow:** `enhance_pressed` → `OverlayWindow` shows a small `QDialog` containing a read-only preview of `enhance-prompt.md` content above two buttons [With screenshot] [Without]; "With screenshot" is disabled if `_screenshot` is `None`; user choice → `OverlayWindow` calls `edit_view.set_enhancing()` + starts `EnhanceWorker`; on `enhanced(text)`, replaces text box content and calls `set_idle()`.

**Mic right-click:** `OverlayWindow` receives `mic_right_clicked`, builds a `QMenu` from `list_input_devices()`, shows it at cursor, and on selection calls `recorder.set_device(idx)` (restarts stream if recording).

---

## Threading overview

```
Main thread (Qt event loop)
│
├── HotkeyBridge.triggered  ← pynput thread (daemon)
│
├── OverlayWindow
│     ├── AudioRecorder (sounddevice callback thread → Qt signal via invokeMethod)
│     ├── TranscribeWorker (QThread)
│     └── EnhanceWorker (QThread)
│
└── insert_text() — called via QTimer.singleShot, runs in main thread
```

Only one `TranscribeWorker` and one `EnhanceWorker` should be active at a time. The UI disables the triggering button until the worker emits its result signal.

---

## Default prompt content

### `enhance-prompt.md` (built-in default)

```
You are a writing assistant. The user has dictated text using voice recognition.
Clean up transcription errors, fix punctuation and capitalization, and structure
the text naturally. Preserve the user's intended meaning exactly.
Output only the improved text — no explanations, no preamble.
```

**Screenshot context sentence** (appended programmatically to the system prompt when a screenshot is included, not part of the file):

```
The provided screenshot can but must not necessarily correspond to the text you
shall reformulate. If it does not feel useful, ignore it; it is just additional
context for you.
```
