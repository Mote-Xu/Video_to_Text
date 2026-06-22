"""Shared data models for the video-to-text pipeline."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VideoMeta:
    """Metadata about the input video."""
    path: Path
    filename: str
    duration_sec: float
    fps: float
    width: int
    height: int
    codec: str = ""
    has_audio: bool = True


@dataclass
class TranscriptSegment:
    """A single transcribed utterance with timestamps."""
    start_sec: float
    end_sec: float
    text: str
    confidence: float = 1.0
    language: str = ""


@dataclass
class KeyFrame:
    """An extracted keyframe from the video."""
    index: int
    timestamp_sec: float
    image_path: Path


@dataclass
class OcrResult:
    """OCR result for text found in a keyframe."""
    text: str
    confidence: float
    frame_index: int
    timestamp_sec: float


@dataclass
class SceneDescription:
    """Vision model's description of a keyframe."""
    frame_index: int
    timestamp_sec: float
    summary: str
    objects: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    setting: str = ""
    on_screen_text: str = ""


@dataclass
class PipelineStats:
    """Timing and cost statistics for the pipeline run."""
    audio_extraction_sec: float = 0.0
    asr_transcription_sec: float = 0.0
    keyframe_extraction_sec: float = 0.0
    ocr_sec: float = 0.0
    vision_sec: float = 0.0
    total_sec: float = 0.0
    vision_tokens_used: int = 0


@dataclass
class PipelineResult:
    """Aggregate result from a full pipeline run."""
    video: VideoMeta
    transcript: list[TranscriptSegment] = field(default_factory=list)
    keyframes: list[KeyFrame] = field(default_factory=list)
    ocr_results: list[OcrResult] = field(default_factory=list)
    scene_descriptions: list[SceneDescription] = field(default_factory=list)
    stats: PipelineStats = field(default_factory=PipelineStats)
    errors: list[str] = field(default_factory=list)
