# Quack Yapper — Implementation Plan

## Quick reference

| Doc | Contents |
|-----|----------|
| [README.md](README.md) | Project structure, dependency list, implementation phases |
| [components.md](components.md) | Per-module spec, interfaces, threading model, key decisions |

---

## Project structure

```
quack-yapper/
├── quack_yapper/
│   ├── __main__.py              # python -m quack_yapper entry point
│   ├── app.py                   # QApplication bootstrap, wires hotkey → overlay
│   ├── config.py                # TOML config load + defaults + prompt file resolution
│   ├── hotkey.py                # Global hotkey listener (pynput)
│   ├── screenshot.py            # Silent fullscreen capture on overlay open
│   ├── audio.py                 # sounddevice capture; emits amplitude chunks
│   ├── transcribe.py            # faster-whisper wrapper; runs in QThread
│   ├── llm_adapter.py           # LLMAdapter ABC + OpenAI / Bedrock concrete adapters
│   ├── ai_enhance.py            # EnhanceWorker (QThread) — calls LLMAdapter.complete()
│   ├── insert.py                # Clipboard write + Ctrl+V simulation via pynput
│   └── overlay/
│       ├── window.py            # Frameless always-on-top QWidget; hosts EditView
│       └── edit_view.py         # Single persistent view: text box + status strip + toolbar
├── docs/
│   ├── TODOs.md
│   ├── tasks/
│   └── plan/                    # ← you are here
├── pyproject.toml       # UV-managed; no requirements.txt
└── README.md
```

---

## Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `PySide6` | UI framework | Overlay window, widgets, threading primitives |
| `faster-whisper` | Local transcription | CUDA optional; model downloaded on first run |
| `sounddevice` | Audio capture | Cross-platform; uses PortAudio under the hood |
| `pynput` | Global hotkey | Works on Windows + Linux without root |
| `httpx` | LLM API calls | Async not required; synchronous call in QThread |
| `tomllib` / `tomli` | TOML config parsing | `tomllib` is stdlib ≥ 3.11; `tomli` backport otherwise |
| `mss` | Screenshot capture | Cross-platform; fastest capture option; works on X11 and Windows; no Pillow needed |

> No focus-restore library needed. When the overlay hides, the OS naturally returns focus to the previously active window. `pynput` (already a dep) then simulates Ctrl+V into that window.

---

## Implementation phases

### Phase 1 — Project scaffold
**Goal:** `python -m quack_yapper` starts without errors.

- [ ] `pyproject.toml` with metadata, `[project.scripts]` entry point — managed with **uv** (`uv sync` is the only install step; no `requirements.txt`); requires Python ≥ 3.11 (`tomllib` is stdlib, `X | Y` union syntax works)

  ```toml
  [project]
  requires-python = ">=3.11"
  dependencies = [
      "PySide6",
      "sounddevice",
      "numpy",
      "faster-whisper",
      "httpx",
      "mss",
      "pynput",
      "boto3",
  ]
  ```
- [ ] `quack_yapper/__main__.py` → calls `app.main()`
- [ ] `quack_yapper/app.py` → creates `QApplication`, calls `sys.exit(app.exec())`
- [ ] `quack_yapper/config.py` → loads `~/.config/quack-yapper/config.toml`; writes defaults if missing; exposes typed `Config` dataclass
- [ ] Default config auto-created with all keys and inline comments
- [ ] Default prompt file (`enhance-prompt.md`) written to `~/.config/quack-yapper/` if missing

---

### Phase 2 — Overlay skeleton + hotkey
**Goal:** Hotkey opens/closes a frameless window containing an empty `EditView`.

- [ ] `quack_yapper/hotkey.py` — wraps `pynput.keyboard.GlobalHotKeys`; emits a Qt signal via a bridge object (pynput runs in its own thread)
- [ ] `quack_yapper/overlay/window.py` — `QWidget` with flags `FramelessWindowHint | WindowStaysOnTopHint | Tool`; centers on active screen; hosts `EditView` as its sole child
- [ ] First hotkey press: show window + immediately start recording (mic button activates)
- [ ] Second hotkey press: if recording → stop; if editing → start recording again at cursor
- [ ] Escape or × closes window and clears state
- [ ] Basic drag-to-move: `mousePressEvent` / `mouseMoveEvent`

---

### Phase 3 — Audio capture + inline waveform
**Goal:** Mic button (or hotkey) starts recording; waveform strip appears inside the edit view.

- [ ] `quack_yapper/audio.py` — `AudioRecorder` class:
  - `start(device=None)` opens a `sounddevice.InputStream` callback
  - Callback emits `amplitude_updated(float)` Qt signal (via bridge) for UI
  - Callback accumulates raw PCM frames into an in-memory buffer
  - `stop() -> Path` flushes buffer, writes WAV to `tempfile.NamedTemporaryFile`, returns path
- [ ] `EditView` recording state:
  - Mic button turns into a stop/recording indicator (red, pulsing or icon change)
  - Status strip (between text box and toolbar) appears, showing a live `WaveformWidget`
  - `WaveformWidget`: custom `QWidget`, `paintEvent` draws scrolling bar chart at 30 Hz
- [ ] Right-click on mic button opens a `QMenu` listing `sounddevice.query_devices(kind="input")` devices; selecting one mid-recording restarts the stream on the new device

---

### Phase 4 — Transcription
**Goal:** After recording stops, the waveform strip becomes a "Transcribing…" indicator; transcribed text is inserted at the cursor.

- [ ] `quack_yapper/transcribe.py` — `TranscribeWorker(QThread)`:
  - Accepts WAV path + whisper config
  - Loads `WhisperModel` on first call (cached as module-level singleton to avoid reload penalty)
  - Emits `transcription_ready(str)` on success, `transcription_failed(str)` on error
- [ ] `EditView` transcribing state:
  - `WaveformWidget` hidden; status strip shows an animated `"Transcribing…"` label (braille spinner + text)
  - Toolbar buttons disabled during transcription
- [ ] On `transcription_ready`: `EditView.insert_at(cursor_pos, text)` — inserts at the position that was recorded when mic button was pressed; status strip hides; toolbar re-enables
- [ ] `quack_yapper/overlay/edit_view.py` — `EditView(QWidget)` layout (see components.md)

---

### Phase 5 — Insert
**Goal:** Insert toolbar button copies full text box content to clipboard, closes the overlay, and pastes at the original cursor position.

- [ ] `quack_yapper/insert.py` — `insert_text(text: str)`:
  1. `QApplication.clipboard().setText(text)`
  2. `OverlayWindow.hide()` — OS immediately returns focus to the previously active window
  3. `QTimer.singleShot(80, _paste)` — brief delay lets the window-manager complete the focus handoff
  4. `_paste`: `pynput.keyboard.Controller()` presses and releases `Key.ctrl + 'v'` — cross-platform, no `pywin32` or `xdotool` needed
- [ ] Clipboard is **not** cleared — intentional per spec

---

### Phase 6 — AI Enhance + screenshot
**Goal:** AI Enhance button sends text (and optionally screenshot) to LLM; result replaces text box.

- [ ] `quack_yapper/screenshot.py` — `capture() -> QPixmap`:
  - Called silently when overlay first opens (before window becomes visible)
  - Uses `mss.mss()` — cross-platform, works on X11 and Windows; `mss` BGRA buffer → `QImage(Format_RGBA8888)` → `QPixmap`
  - Returns `None` on Wayland or any failure; result stored in `OverlayWindow._screenshot`
- [ ] `quack_yapper/llm_adapter.py` — `LLMAdapter` ABC + `OpenAIAdapter` + `BedrockAdapter` + `make_adapter()`; see `components.md`
- [ ] `quack_yapper/ai_enhance.py` — `EnhanceWorker(QThread)`:
  - Calls `adapter.complete(system_prompt, text, image_bytes)` — blocking, 5 min timeout
  - Emits `enhanced(str)`, `enhance_failed(str)`, or `cancelled()`
  - Exposes `cancel()` method that closes the adapter’s connection
- [ ] `OverlayWindow` shows `QDialog` with prompt preview + [With screenshot] / [Without] buttons; converts `QPixmap` → raw PNG bytes before passing to worker
- [ ] On `enhanced`: replace `QPlainTextEdit` content, call `set_idle()`
- [ ] On `cancelled` / `enhance_failed`: call `set_idle()` (failed also shows brief error in bottom zone)

---

### Phase 7 — Polish + packaging
**Goal:** Installable, user-friendly, error-resilient.

- [ ] Graceful error toasts: `QToolTip` or inline label for transcription/LLM errors
- [ ] Whisper model download progress shown in transcribing view
- [ ] Config validation on startup: warn on unknown keys, fill missing keys with defaults
- [ ] `pyproject.toml` `[project.scripts]`: `quack-yapper = "quack_yapper.__main__:main"`
- [ ] `README.md` install section: `uv sync` + `uv run quack-yapper` (or `uv pip install -e .` for a system-wide install) + first-run config location
- [ ] Optional: `PyInstaller` one-file build for distribution without Python install

---

## State machine summary

The window is always showing `EditView`. States are internal to the view, not separate screens.

```
[window hidden]
     │  hotkey
     ▼
  EDITING ◄───────────────────────────────────► [window hidden]
  (toolbar enabled,                       Insert / Escape / ×
   status strip hidden)
     │  mic button OR hotkey
     │  (saves cursor pos)
     ▼
  RECORDING
  (mic button = stop, waveform in strip)
     │  mic button / hotkey
     ▼
  TRANSCRIBING
  ("Transcribing…" in strip, toolbar disabled)
     │  transcription_ready
     ▼
  EDITING  (text inserted at saved cursor pos, strip hides)
```

---

## Key technical decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Package manager | `uv` | Single `pyproject.toml`; no `requirements.txt`; `uv sync` for reproducible installs |
| Global hotkey + key simulation | `pynput` | One library covers both: global hotkey listener and outgoing Ctrl+V simulation; no `pywin32` or `xdotool` needed |
| Audio I/O | `sounddevice` | Thin NumPy-friendly wrapper over PortAudio; non-blocking callback API |
| Whisper model singleton | Module-level cache | Avoids 1–3 s reload on every transcription; GIL is released during inference |
| LLM call | Synchronous `httpx` in `QThread` | Simpler than async; timeout configurable; no event loop nesting |
| Screenshot library | `mss` | Cross-platform (Windows + Linux X11); fastest capture; no Pillow dep |
| Screenshot timing | Before window is shown | Prevents the overlay itself from appearing in the screenshot |
| Insert / focus | Hide overlay → OS returns focus → `pynput` sends Ctrl+V | No window-ID bookkeeping; simpler and more reliable across WMs |
| Clipboard not cleared | Intentional | User may want to paste again manually after the overlay closes |

---

## UI mockups

All states live inside the same window. Only the status strip and toolbar button states change.

The bottom zone is a single fixed-height `QStackedWidget`. It swaps between the toolbar, the waveform, and the transcribing label — always occupying the same space.

### Idle / editing

```
┌──────────────────────────────────────────────┐
│                                            × │
│  ┌──────────────────────────────────────┐   │
│  │ So I was thinking we could move the  │   │
│  │ meeting to Thursday| and also include │   │
│  │ the design team in the discussion.    │   │
│  ├──────────────────────────────────────┤   │
│  │    [ 🎤 ]       [ ✨ ]       [ ➜ ]   │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

`|` = text cursor. `🎤` = mic, `✨` = AI enhance, `➜` = insert.
- Text box starts empty when window opens from hidden state.
- Right-click `🎤` opens a `QMenu` for device selection.

---

### Recording (mic pressed or hotkey)

```
┌──────────────────────────────────────────────┐
│                                            × │
│  ┌──────────────────────────────────────┐   │
│  │ So I was thinking we could move the  │   │
│  │ meeting to Thursday| and also include │   │
│  │ the design team in the discussion.    │   │
│  ├──────────────────────────────────────┤   │
│  │  ▁▂▄▆█▇▅▃▁▂▄▇█▆▃▁▂▄▅▃▁▂▄▆█  [⏹]  │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

- Bottom zone swaps to `WaveformWidget`; cursor pos saved at mic-press time.
- Text box is non-editable while recording.
- `[⏹]` in the waveform row is the stop button; hotkey also stops.

---

### Transcribing

```
┌──────────────────────────────────────────────┐
│                                            × │
│  ┌──────────────────────────────────────┐   │
│  │ So I was thinking we could move the  │   │
│  │ meeting to Thursday| and also include │   │
│  │ the design team in the discussion.    │   │
│  ├──────────────────────────────────────┤   │
│  │       ⣷  Transcribing…               │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

- Same zone, now shows spinner + label. No buttons visible.
- Text box is non-editable while transcribing.

---

### After transcription (back to idle/editing)

```
┌──────────────────────────────────────────────┐
│                                            × │
│  ┌──────────────────────────────────────┐   │
│  │ So I was thinking we could move the  │   │
│  │ meeting to Thursday morning| and     │   │
│  │ also include the design team in the  │   │
│  │ discussion.                          │   │
│  ├──────────────────────────────────────┤   │
│  │    [ 🎤 ]        [ ✨ ]        [ ➜ ]  │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

- "morning" inserted at saved cursor pos; bottom zone snaps back to toolbar; text box re-enables.

---

### AI Enhance popup

Small `QDialog` (or `QMenu`) that appears when `✨` is clicked:

```
┌─────────────────────────────────────────────┐
│  ┌──────────────────────────────────────┐   │
│  │ Reformulate the text to be more clear│   │
│  │ and concise... (prompt for enhance)  │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  [ With screenshot ]          [ Without ]   │
└─────────────────────────────────────────────┘
```

- Prompt box shows the current contents of `enhance-prompt.md` as a read-only preview.
- "With screenshot" is greyed-out if capture failed.
- After choice: bottom zone switches to the Enhancing slot (see below); text box goes non-editable.

---

### Enhancing (AI Enhance running)

```
┌──────────────────────────────────────────────┐
│                                            × │
│  ┌──────────────────────────────────────┐   │
│  │ So I was thinking we could move the  │   │
│  │ meeting to Thursday and also include  │   │
│  │ the design team in the discussion.    │   │
│  ├──────────────────────────────────────┤   │
│  │  ⣷  Enhancing…                  [✕]  │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

- `[✕]` cancels the in-flight request silently (original text kept, toolbar re-enables, no error shown).
