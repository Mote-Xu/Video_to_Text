"""Configuration management — loads config.yaml, .env, and applies CLI overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class AudioConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1


class AsrConfig(BaseModel):
    engine: str = "faster-whisper"
    model_size: str = "small"          # tiny / base / small / medium
    device: str = "cuda"
    compute_type: str = "float16"      # float16 / int8_float16
    language: str | None = None        # None = auto-detect
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = True


class KeyFrameConfig(BaseModel):
    interval_sec: float = 5.0          # extract a frame every N seconds
    format: str = "jpg"
    quality: int = 90
    max_keyframes: int = 2000


class OcrConfig(BaseModel):
    engine: str = "paddleocr"
    lang: str = "ch"                   # PaddleOCR: "ch" = Chinese + English
    use_gpu: bool = False              # default CPU to avoid VRAM conflict
    conf_threshold: float = 0.5


class VisionConfig(BaseModel):
    provider: str = "deepseek"          # deepseek / anthropic / openai
    model: str = "deepseek-chat"
    max_tokens: int = 200
    temperature: float = 0.3
    batch_size: int = 1                # frames per API call


class OutputConfig(BaseModel):
    dir: str = "./outputs"
    formats: list[str] = ["json", "markdown"]
    srt_max_chars_per_line: int = 42


class PipelineConfig(BaseModel):
    video: AudioConfig = Field(default_factory=AudioConfig)     # shared audio settings
    asr: AsrConfig = Field(default_factory=AsrConfig)
    keyframe: KeyFrameConfig = Field(default_factory=KeyFrameConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    # Secrets (loaded from .env)
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_YAML = Path(__file__).parent / "config.yaml"


def load_config(
    config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> PipelineConfig:
    """
    Load configuration in priority order: config.yaml → .env → CLI args.

    Parameters
    ----------
    config_path : Path to a YAML config file (defaults to ./config.yaml).
    cli_overrides: Dict of key paths like ``{"asr.model_size": "medium"}``.
    """
    # 1. Load .env
    load_dotenv()

    # 2. Load YAML defaults
    yaml_path = Path(config_path) if config_path else DEFAULT_CONFIG_YAML
    yaml_data: dict[str, Any] = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    # 3. Merge in env secrets
    env_data: dict[str, Any] = {}
    if api_key := os.getenv("DEEPSEEK_API_KEY"):
        env_data["deepseek_api_key"] = api_key
    if api_key := os.getenv("ANTHROPIC_API_KEY"):
        env_data["anthropic_api_key"] = api_key

    # 4. Build config dict with nested structure
    config_dict: dict[str, Any] = {
        "video": (yaml_data.get("audio") or {}),
        "asr": (yaml_data.get("asr") or {}),
        "keyframe": (yaml_data.get("keyframe") or {}),
        "ocr": (yaml_data.get("ocr") or {}),
        "vision": (yaml_data.get("vision") or {}),
        "output": (yaml_data.get("output") or {}),
        "deepseek_api_key": env_data.get("deepseek_api_key", ""),
        "anthropic_api_key": env_data.get("anthropic_api_key", ""),
    }

    # 5. Apply CLI overrides (dot-notation keys like "asr.model_size")
    if cli_overrides:
        for key, value in cli_overrides.items():
            parts = key.split(".", 1)
            if len(parts) == 2:
                section, field = parts
                if section in config_dict and isinstance(config_dict[section], dict):
                    config_dict[section][field] = value

    return PipelineConfig(**config_dict)
