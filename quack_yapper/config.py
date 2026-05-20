from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "quack-yapper"
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROMPT_FILE = CONFIG_DIR / "enhance-prompt.md"
MODELS_DIR = CONFIG_DIR / "models"

_DEFAULT_CONFIG_TOML = """\
[hotkeys]
toggle_recording = "ctrl+shift+z"

[ui]
theme = "dark"  # dark | light

[ai_enhance]
provider = "openai"           # "openai" (Ollama / OpenAI / Azure) or "bedrock"
model = "granite4:micro-h"
base_url = "http://localhost:11434/v1"  # OpenAI: /v1 endpoint
api_key = ""
region = "us-east-1"          # Bedrock only

[audio]
input_device = ""  # empty = system default; set to device name to persist selection

[whisper]
model = "base"   # tiny, base, small, medium, large
device = "auto"  # auto, cpu, cuda
"""

_DEFAULT_PROMPT = """\
You are a writing assistant. The user has dictated text using voice recognition.
Clean up transcription errors, fix punctuation and capitalization, and structure
the text naturally. Preserve the user's intended meaning exactly.
Output only the improved text — no explanations, no preamble.
"""

_SCREENSHOT_CONTEXT_SENTENCE = (
    "The provided screenshot can but must not necessarily correspond to the text you "
    "shall reformulate. If it does not feel useful, ignore it; it is just additional "
    "context for you."
)


@dataclass
class WhisperConfig:
    model: str = "base"
    device: str = "auto"


@dataclass
class AIConfig:
    provider: str = "openai"
    model: str = "granite4:micro-h"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    region: str = "us-east-1"


@dataclass
class HotkeyConfig:
    toggle_recording: str = "ctrl+shift+z"


@dataclass
class UIConfig:
    theme: str = "dark"  # "dark" | "light"


@dataclass
class AudioConfig:
    input_device: str = ""  # empty = system default; stores device name


@dataclass
class Config:
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    ai_enhance: AIConfig = field(default_factory=AIConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)


def _ensure_defaults() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(_DEFAULT_CONFIG_TOML, encoding="utf-8")
        logger.info("Created default config: %s", CONFIG_FILE)
    if not PROMPT_FILE.exists():
        PROMPT_FILE.write_text(_DEFAULT_PROMPT, encoding="utf-8")
        logger.info("Created default prompt file: %s", PROMPT_FILE)


def load() -> Config:
    _ensure_defaults()
    raw = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    hotkeys_raw = raw.get("hotkeys", {})
    whisper_raw = raw.get("whisper", {})
    ai_raw = raw.get("ai_enhance", {})

    hotkeys = HotkeyConfig(
        toggle_recording=hotkeys_raw.get("toggle_recording", "ctrl+shift+y"),
    )
    whisper = WhisperConfig(
        model=whisper_raw.get("model", "base"),
        device=whisper_raw.get("device", "auto"),
    )
    ai_enhance = AIConfig(
        provider=ai_raw.get("provider", "openai"),
        model=ai_raw.get("model", "llama3.2"),
        base_url=ai_raw.get("base_url", "http://localhost:11434/v1"),
        api_key=ai_raw.get("api_key", ""),
        region=ai_raw.get("region", "us-east-1"),
    )

    ui_raw = raw.get("ui", {})
    ui = UIConfig(
        theme=ui_raw.get("theme", "dark"),
    )

    audio_raw = raw.get("audio", {})
    audio = AudioConfig(
        input_device=audio_raw.get("input_device", ""),
    )

    return Config(hotkeys=hotkeys, whisper=whisper, ai_enhance=ai_enhance, ui=ui, audio=audio)


def save(config: Config) -> None:
    """Rewrite config.toml from the current Config state."""
    content = (
        f'[hotkeys]\n'
        f'toggle_recording = "{config.hotkeys.toggle_recording}"\n'
        f'\n'
        f'[ui]\n'
        f'theme = "{config.ui.theme}"  # dark | light\n'
        f'\n'
        f'[audio]\n'
        f'input_device = "{config.audio.input_device}"\n'
        f'\n'
        f'[ai_enhance]\n'
        f'provider = "{config.ai_enhance.provider}"\n'
        f'model = "{config.ai_enhance.model}"\n'
        f'base_url = "{config.ai_enhance.base_url}"\n'
        f'api_key = "{config.ai_enhance.api_key}"\n'
        f'region = "{config.ai_enhance.region}"\n'
        f'\n'
        f'[whisper]\n'
        f'model = "{config.whisper.model}"\n'
        f'device = "{config.whisper.device}"\n'
    )
    CONFIG_FILE.write_text(content, encoding="utf-8")
    logger.debug("Config saved to %s", CONFIG_FILE)


def enhance_prompt() -> str:
    if not PROMPT_FILE.exists():
        logger.warning("Prompt file not found: %s. Using built-in default.", PROMPT_FILE)
        return _DEFAULT_PROMPT
    return PROMPT_FILE.read_text(encoding="utf-8")


def screenshot_context_sentence() -> str:
    return _SCREENSHOT_CONTEXT_SENTENCE
