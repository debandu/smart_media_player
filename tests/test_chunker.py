"""Tests for Transcribe/VideoChunker.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from Transcribe.VideoChunker import VideoChunker


# ---------------------------------------------------------------------------
# _get_duration
# ---------------------------------------------------------------------------

class TestGetDuration:
    def test_parses_ffprobe_stdout(self):
        mock_result = MagicMock()
        mock_result.stdout = "120.5\n"
        with patch("subprocess.run", return_value=mock_result):
            duration = VideoChunker()._get_duration(Path("/fake/video.mp4"))
        assert duration == pytest.approx(120.5)

    def test_passes_correct_ffprobe_command(self):
        mock_result = MagicMock()
        mock_result.stdout = "60.0\n"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            VideoChunker()._get_duration(Path("/fake/video.mp4"))
        args = mock_run.call_args[0][0]
        assert args[0] == "ffprobe"
        assert str(Path("/fake/video.mp4")) in args


# ---------------------------------------------------------------------------
# split_iter — chunk shape and timing
# ---------------------------------------------------------------------------

class TestSplitIterShape:
    def test_single_chunk_when_video_shorter_than_duration(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=45.0), \
             patch("subprocess.run"):
            chunks = list(chunker.split_iter("/fake/video.mp4"))
        assert len(chunks) == 1
        path, start, end = chunks[0]
        assert start == 0.0
        assert end == pytest.approx(45.0)

    def test_multiple_chunks_for_long_video(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=150.0), \
             patch("subprocess.run"):
            chunks = list(chunker.split_iter("/fake/video.mp4"))
        assert len(chunks) == 3

    def test_chunk_boundaries_are_contiguous(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=150.0), \
             patch("subprocess.run"):
            chunks = list(chunker.split_iter("/fake/video.mp4"))
        starts = [c[1] for c in chunks]
        ends = [c[2] for c in chunks]
        # each start matches the previous end
        for i in range(1, len(chunks)):
            assert starts[i] == pytest.approx(ends[i - 1])

    def test_last_chunk_end_equals_total_duration(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=130.0), \
             patch("subprocess.run"):
            chunks = list(chunker.split_iter("/fake/video.mp4"))
        assert chunks[-1][2] == pytest.approx(130.0)

    def test_chunk_filenames_are_zero_padded(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=180.0), \
             patch("subprocess.run"):
            chunks = list(chunker.split_iter("/fake/video.mp4"))
        names = [c[0].name for c in chunks]
        assert names == ["chunk_0000.wav", "chunk_0001.wav", "chunk_0002.wav"]

    def test_paths_are_wav_files(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=90.0), \
             patch("subprocess.run"):
            chunks = list(chunker.split_iter("/fake/video.mp4"))
        for path, _, _ in chunks:
            assert path.suffix == ".wav"


# ---------------------------------------------------------------------------
# split_iter — ffmpeg invocation
# ---------------------------------------------------------------------------

class TestSplitIterFfmpeg:
    def test_ffmpeg_called_once_per_chunk(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=120.0), \
             patch("subprocess.run") as mock_run:
            list(chunker.split_iter("/fake/video.mp4"))
        assert mock_run.call_count == 2

    def test_ffmpeg_uses_correct_start_times(self):
        chunker = VideoChunker(chunk_duration=60)
        calls_made = []

        def capture(cmd, **kwargs):
            calls_made.append(cmd)

        with patch.object(chunker, "_get_duration", return_value=120.0), \
             patch("subprocess.run", side_effect=capture):
            list(chunker.split_iter("/fake/video.mp4"))

        # first call: -ss 0.0
        assert "0.0" in calls_made[0]
        # second call: -ss 60.0
        assert "60.0" in calls_made[1]

    def test_ffmpeg_extracts_audio_only(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=60.0), \
             patch("subprocess.run") as mock_run:
            list(chunker.split_iter("/fake/video.mp4"))
        cmd = mock_run.call_args[0][0]
        # -vn suppresses the video stream
        assert "-vn" in cmd


# ---------------------------------------------------------------------------
# split_iter — file lifecycle
# ---------------------------------------------------------------------------

class TestSplitIterFileLifecycle:
    def _create_fake_ffmpeg(self):
        """Side-effect that actually creates the output wav file."""
        def fake_ffmpeg(cmd, **kwargs):
            Path(cmd[-1]).touch()
        return fake_ffmpeg

    def test_chunk_file_exists_during_yield(self):
        chunker = VideoChunker(chunk_duration=60)
        with patch.object(chunker, "_get_duration", return_value=30.0), \
             patch("subprocess.run", side_effect=self._create_fake_ffmpeg()):
            for chunk_path, _, _ in chunker.split_iter("/fake/video.mp4"):
                assert chunk_path.exists()

    def test_chunk_file_deleted_after_yield(self):
        chunker = VideoChunker(chunk_duration=60)
        seen_paths = []
        with patch.object(chunker, "_get_duration", return_value=30.0), \
             patch("subprocess.run", side_effect=self._create_fake_ffmpeg()):
            for chunk_path, _, _ in chunker.split_iter("/fake/video.mp4"):
                seen_paths.append(chunk_path)
        for p in seen_paths:
            assert not p.exists(), f"{p} was not deleted after its yield"
