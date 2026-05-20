# 01 — Quack Yapper Core

**Status:** 💡 Idea

## What it is

A standalone desktop overlay tool for system-wide voice dictation and AI-enhanced text insertion. Fully independent — no runtime dependency on Quack Norris or any other tool.

## User workflow

1. User is in any app (e.g. Teams, VS Code, browser) with cursor in a text field
2. User presses the Yapper hotkey
3. A small overlay appears showing:
   - A recording icon
   - Live amplitude / waveform visualization
4. User dictates freely
5. User presses the hotkey again **or** clicks the overlay icon
6. Overlay switches to "transcribing" state
7. Transcribed text appears in an editable input box
8. User can:
   - **Continue dictating** — appends more transcribed text to the box
   - **Edit manually** — type directly in the box
   - **AI Enhance** — sends the raw text to an LLM that structures and cleans it
   - **Insert** — copies the final text to clipboard, closes the overlay, pastes at the original cursor position

## Screenshot context feature

- When the Yapper overlay opens, a screenshot is **silently captured** (before the window appears)
- When `✨` is clicked, a small `QDialog` shows a read-only preview of the current `enhance-prompt.md` and two buttons: **[With screenshot]** / **[Without]**
- [With screenshot] is greyed-out if capture failed (e.g. Wayland)
- The screenshot context instruction is appended to the system prompt programmatically — not baked into the prompt file
- A **cancel button** `[✕]` appears in the bottom zone while the LLM call is in flight; cancelling silently restores the original text

### Security note

Screenshot requires an explicit user action (clicking [With screenshot]) — it is never sent automatically. Screenshots can contain sensitive information (passwords, private messages, confidential documents).

## Stack

Fully self-contained. No shared code with Quack Norris 3.0.

- **UI** — PySide6 (familiar from Quack Norris 2.0, proven on Windows and Linux)
- **Transcription** — faster-whisper (local, offline, CUDA optional)
- **LLM** — `httpx` for OpenAI-compatible APIs (Ollama, OpenAI, Azure); `boto3` for AWS Bedrock Converse
- **Text insertion** — clipboard + simulated keypress

## Configuration

Config file lives at `~/.config/quack-yapper/config.toml`. No settings UI — edit manually.

```toml
[hotkeys]
toggle_recording = "ctrl+shift+y"

[ai_enhance]
provider = "openai"   # "openai" (Ollama / OpenAI / Azure) or "bedrock"
model = "llama3.2"
base_url = "http://localhost:11434/v1"   # OpenAI: /v1 endpoint; Bedrock: endpoint URL
api_key = ""
region = "us-east-1"                     # Bedrock only

[whisper]
model = "base"  # tiny, base, small, medium, large
device = "auto"  # auto, cpu, cuda
```

### Prompt file

One markdown file next to `config.toml`:

```
~/.config/quack-yapper/
├── config.toml
└── enhance-prompt.md
```

If missing, Yapper falls back to a built-in default prompt and logs a warning. The screenshot context instruction is appended in code — not part of the file.

## Behavior

- Opens blank — no persistent state, always fresh
- Input field only appears after the first transcription
- On Insert: text is copied to clipboard, window closes, pastes at original cursor position
- Clipboard is **not cleared** after insert — user can still paste manually elsewhere
- Hotkey is a **toggle** — press once to start recording, press again to stop and transcribe

## AI Enhance

Single-shot LLM call — no conversation history, no tools, no agent loop:

- Input: raw transcribed text + optionally screenshot (raw PNG bytes)
- System prompt: `enhance-prompt.md`; screenshot context sentence appended programmatically if image is included
- Output: cleaned, structured text replaces the input box content
- Timeout: 5 minutes; on failure or cancel, original text is kept
