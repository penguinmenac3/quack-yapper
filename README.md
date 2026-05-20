# Quack Yapper

A lightweight desktop overlay for system-wide voice dictation with AI-enhanced text insertion.

Press a hotkey anywhere — dictate — enhance with AI — insert at cursor. Works in any app.

---

## What it does

1. Press hotkey → small overlay appears with recording indicator + amplitude visualization
2. Dictate freely
3. Press hotkey again or click overlay → transcription runs locally (faster-whisper)
4. Transcribed text appears in an editable input box
5. Options:
   - **Continue** — dictate more, appends to the box
   - **Edit** — type directly in the box
   - **AI Enhance** — LLM structures and cleans your text
   - **Insert** — copies to clipboard, closes overlay, pastes at original cursor position

## AI Enhance + Screenshot Context

When Yapper opens, a screenshot is silently captured. By default it is **not** sent to the AI. Enable the *"Include screenshot as context"* checkbox to let the AI use it for tone/context matching (e.g. replying in a Teams chat).

## Status

🌱 Early planning — see `docs/TODOs.md`

## Related

- [Quack Norris](https://github.com/...) — AI coding assistant. Quack Yapper pairs well with it for voice-heavy workflows.
