from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Iterator


class VideoChunker:
    """Splits a video into fixed-duration audio-only WAV chunks using ffmpeg."""

    def __init__(self, chunk_duration: int = 60):
        self.chunk_duration = chunk_duration

    def _get_duration(self, video_path: Path) -> float:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())

    def split_iter(self, video_path: str | Path) -> Iterator[tuple[Path, float, float]]:
        """
        Yield (chunk_wav_path, start_sec, end_sec) one chunk at a time.
        Each chunk is extracted just before it is yielded, so the caller can
        transcribe it and delete it before the next one arrives — keeping disk
        usage to a single chunk at a time.
        """
        video_path = Path(video_path)
        total = self._get_duration(video_path)
        tmp_dir = Path(tempfile.mkdtemp(prefix="smp_chunks_"))

        start = 0.0
        idx = 0
        while start < total:
            end = min(start + self.chunk_duration, total)
            chunk_path = tmp_dir / f"chunk_{idx:04d}.wav"

            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-ss", str(start),
                    "-t", str(self.chunk_duration),
                    "-vn", "-ar", "16000", "-ac", "1",
                    str(chunk_path),
                ],
                capture_output=True,
                check=True,
            )

            yield chunk_path, start, end

            # Delete after caller is done with it
            if chunk_path.exists():
                chunk_path.unlink()

            start = end
            idx += 1

        try:
            tmp_dir.rmdir()
        except OSError:
            pass
