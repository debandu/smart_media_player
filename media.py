"""
video_transcript.py

Produces a timestamped transcript for a video by preferring an existing
subtitle (embedded track or sidecar file) over running ASR, since subtitles
are human-authored and more accurate than a model's guess.

Flow:
    1. Look for a sidecar subtitle file (.srt/.vtt/.ass/.ssa/.sub) next to the video.
    2. If none, probe the container for an embedded text-based subtitle stream
       and extract it (bitmap subtitle codecs like PGS/VobSub are skipped —
       those need OCR, not parsing).
    3. If still nothing, fall back to ASR (offline via faster-whisper, or
       online via OpenAI's hosted Whisper API).
    4. Every path returns the same Transcript / TranscriptSegment shape, tagged
       with where it came from ("subtitle" vs "asr").

Dependencies:
    pip install pysubs2 --break-system-packages          # always needed
    pip install faster-whisper --break-system-packages   # only for offline ASR
    pip install openai --break-system-packages           # only for online ASR
    ffmpeg / ffprobe must be on PATH for embedded-subtitle extraction.
"""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import pysubs2

SubtitleSource = Literal["subtitle", "asr"]

# Text-based sidecar/extracted subtitle formats we can parse directly.
TEXT_SUBTITLE_EXTS = (".srt", ".vtt", ".ass", ".ssa", ".sub")

# Bitmap-based subtitle codecs ffprobe may report inside a container.
# These are images, not text — extracting them still requires OCR, so we
# deliberately skip them and fall through to ASR instead.
BITMAP_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str
    source: SubtitleSource


@dataclass
class Transcript:
    segments: list[TranscriptSegment] = field(default_factory=list)
    source: SubtitleSource = "asr"
    language: Optional[str] = None

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            {
                "source": self.source,
                "language": self.language,
                "segments": [s.__dict__ for s in self.segments],
            },
            indent=indent,
        )


# ---------------------------------------------------------------------------
# Subtitle detection + extraction + parsing
# ---------------------------------------------------------------------------

class SubtitleExtractor:
    """Finds and parses an existing subtitle, if the video has one."""

    def find(self, video_path: Path) -> Optional[Transcript]:
        sidecar = self._find_sidecar(video_path)
        if sidecar:
            return Transcript(segments=self._parse(sidecar), source="subtitle")

        stream = self._find_embedded(video_path)
        if stream:
            extracted = self._extract_embedded(video_path, stream["index"])
            language = stream.get("tags", {}).get("language")
            return Transcript(
                segments=self._parse(extracted), source="subtitle", language=language
            )

        return None

    def _find_sidecar(self, video_path: Path) -> Optional[Path]:
        for ext in TEXT_SUBTITLE_EXTS:
            candidate = video_path.with_suffix(ext)
            if candidate.exists():
                return candidate
        return None

    def _find_embedded(self, video_path: Path) -> Optional[dict]:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "s",
                    "-show_entries", "stream=index,codec_name:stream_tags=language",
                    "-of", "json",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

        streams = json.loads(result.stdout).get("streams", [])
        text_streams = [s for s in streams if s.get("codec_name") not in BITMAP_SUBTITLE_CODECS]
        return text_streams[0] if text_streams else None

    def _extract_embedded(self, video_path: Path, stream_index: int) -> Path:
        out_path = video_path.with_suffix(f".extracted_{stream_index}.srt")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-map", f"0:{stream_index}", str(out_path)],
            capture_output=True,
            check=True,
        )
        return out_path

    def _parse(self, subtitle_path: Path) -> list[TranscriptSegment]:
        subs = pysubs2.load(str(subtitle_path))
        segments = []
        for line in subs:
            text = line.plaintext.strip()
            if text:
                segments.append(TranscriptSegment(line.start, line.end, text, source="subtitle"))
        return segments


# ---------------------------------------------------------------------------
# ASR fallback — Strategy interface, matches "Abstract transcribe" in the LLD
# ---------------------------------------------------------------------------

class Transcriber(ABC):
    """Implement this once per backend (offline / online) and swap freely."""

    @abstractmethod
    def transcribe(self, video_path: Path) -> Transcript:
        ...


class WhisperOfflineTranscriber(Transcriber):
    """Offline ASR using faster-whisper. Runs fully locally, no network needed."""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, video_path: Path) -> Transcript:
        from faster_whisper import WhisperModel  # lazy import — optional dependency

        model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        segments_iter, info = model.transcribe(str(video_path))

        segments = [
            TranscriptSegment(
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                text=seg.text.strip(),
                source="asr",
            )
            for seg in segments_iter
        ]
        return Transcript(segments=segments, source="asr", language=info.language)


class OpenAIOnlineTranscriber(Transcriber):
    """Online ASR using OpenAI's hosted Whisper endpoint. Requires OPENAI_API_KEY."""

    def __init__(self, model: str = "whisper-1"):
        self.model = model

    def transcribe(self, video_path: Path) -> Transcript:
        from openai import OpenAI  # lazy import — optional dependency

        client = OpenAI()
        with open(video_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model=self.model, file=f, response_format="verbose_json"
            )

        segments = [
            TranscriptSegment(
                start_ms=int(seg["start"] * 1000),
                end_ms=int(seg["end"] * 1000),
                text=seg["text"].strip(),
                source="asr",
            )
            for seg in response.segments
        ]
        return Transcript(
            segments=segments, source="asr", language=getattr(response, "language", None)
        )


# ---------------------------------------------------------------------------
# Orchestrator — the concrete flow behind "Main menu" calling "Abstract transcribe"
# ---------------------------------------------------------------------------

class TranscriptionPipeline:
    def __init__(self, transcriber: Transcriber, prefer_subtitle: bool = True):
        self.transcriber = transcriber
        self.prefer_subtitle = prefer_subtitle
        self.extractor = SubtitleExtractor()

    def run(self, video_path: str | Path) -> Transcript:
        video_path = Path(video_path)

        if self.prefer_subtitle:
            existing = self.extractor.find(video_path)
            if existing:
                return existing

        return self.transcriber.transcribe(video_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python video_transcript.py <video_path>")
        sys.exit(1)

    # Swap WhisperOfflineTranscriber() for OpenAIOnlineTranscriber() to use the
    # cloud path instead — nothing else in the pipeline needs to change.
    pipeline = TranscriptionPipeline(transcriber=WhisperOfflineTranscriber(model_size="base"))
    result = pipeline.run(sys.argv[1])
    print(result.to_json())