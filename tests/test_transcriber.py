"""Tests for Transcribe/Transcriber.py — data models, subtitle extractor, and pipeline."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from Transcribe.Transcriber import (
    Transcript,
    TranscriptSegment,
    SubtitleExtractor,
    TranscriptionPipeline,
    WhisperOfflineTranscriber,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class TestTranscriptSegment:
    def test_fields_stored(self):
        seg = TranscriptSegment(start_ms=1000, end_ms=3000, text="Hello", source="asr")
        assert seg.start_ms == 1000
        assert seg.end_ms == 3000
        assert seg.text == "Hello"
        assert seg.source == "asr"


class TestTranscript:
    def _make_transcript(self):
        segs = [
            TranscriptSegment(0, 1000, "Hi", "asr"),
            TranscriptSegment(1000, 2000, "there", "asr"),
        ]
        return Transcript(segments=segs, source="asr", language="en")

    def test_to_json_valid(self):
        t = self._make_transcript()
        data = json.loads(t.to_json())
        assert data["source"] == "asr"
        assert data["language"] == "en"
        assert len(data["segments"]) == 2

    def test_to_json_segment_fields(self):
        t = self._make_transcript()
        data = json.loads(t.to_json())
        seg = data["segments"][0]
        assert seg["start_ms"] == 0
        assert seg["end_ms"] == 1000
        assert seg["text"] == "Hi"

    def test_empty_transcript(self):
        t = Transcript()
        data = json.loads(t.to_json())
        assert data["segments"] == []

    def test_default_source_is_asr(self):
        t = Transcript()
        assert t.source == "asr"


# ---------------------------------------------------------------------------
# SubtitleExtractor
# ---------------------------------------------------------------------------

class TestSubtitleExtractor:
    def setup_method(self):
        self.extractor = SubtitleExtractor()
        self.video = Path("/fake/movie.mp4")

    def test_find_returns_none_when_no_subtitle(self):
        with patch.object(self.extractor, "_find_sidecar", return_value=None), \
             patch.object(self.extractor, "_find_embedded", return_value=None):
            result = self.extractor.find(self.video)
        assert result is None

    def test_find_prefers_sidecar_over_embedded(self):
        sidecar = Path("/fake/movie.srt")
        fake_segments = [TranscriptSegment(0, 1000, "Sub text", "subtitle")]
        with patch.object(self.extractor, "_find_sidecar", return_value=sidecar), \
             patch.object(self.extractor, "_parse", return_value=fake_segments):
            result = self.extractor.find(self.video)
        assert result is not None
        assert result.source == "subtitle"
        assert result.segments[0].text == "Sub text"

    def test_find_sidecar_detects_existing_srt(self, tmp_path):
        video = tmp_path / "film.mp4"
        srt = tmp_path / "film.srt"
        srt.write_text("[Script Info]")
        result = self.extractor._find_sidecar(video)
        assert result == srt

    def test_find_sidecar_returns_none_when_absent(self, tmp_path):
        video = tmp_path / "film.mp4"
        result = self.extractor._find_sidecar(video)
        assert result is None

    def test_find_embedded_returns_none_on_ffprobe_failure(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = self.extractor._find_embedded(self.video)
        assert result is None

    def test_find_embedded_skips_bitmap_subtitles(self):
        ffprobe_output = json.dumps({
            "streams": [{"index": 0, "codec_name": "dvd_subtitle"}]
        })
        mock_result = MagicMock()
        mock_result.stdout = ffprobe_output
        with patch("subprocess.run", return_value=mock_result):
            result = self.extractor._find_embedded(self.video)
        assert result is None

    def test_find_embedded_returns_text_subtitle_stream(self):
        ffprobe_output = json.dumps({
            "streams": [{"index": 2, "codec_name": "subrip", "tags": {"language": "eng"}}]
        })
        mock_result = MagicMock()
        mock_result.stdout = ffprobe_output
        with patch("subprocess.run", return_value=mock_result):
            result = self.extractor._find_embedded(self.video)
        assert result is not None
        assert result["index"] == 2

    def test_find_embedded_handles_subprocess_error(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe")):
            result = self.extractor._find_embedded(self.video)
        assert result is None

    def test_parse_returns_segments(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nGoodbye\n\n"
        )
        segments = self.extractor._parse(srt)
        assert len(segments) == 2
        assert segments[0].text == "Hello world"
        assert segments[1].text == "Goodbye"
        assert all(s.source == "subtitle" for s in segments)

    def test_parse_preserves_cue_timings(self, tmp_path):
        srt = tmp_path / "timed.srt"
        srt.write_text("1\n00:00:01,500 --> 00:00:03,250\nTimed line\n\n")
        segments = self.extractor._parse(srt)
        assert segments[0].start_ms == 1500
        assert segments[0].end_ms == 3250

    def test_parse_skips_blank_cues(self, tmp_path):
        """Whitespace-only subtitle cues must not become empty segments."""
        srt = tmp_path / "blanks.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\n   \n\n"
            "3\n00:00:07,000 --> 00:00:09,000\nGoodbye\n\n"
        )
        segments = self.extractor._parse(srt)
        assert [s.text for s in segments] == ["Hello world", "Goodbye"]


# ---------------------------------------------------------------------------
# TranscriptionPipeline
# ---------------------------------------------------------------------------

class TestTranscriptionPipeline:
    def _fake_transcript(self):
        return Transcript(
            segments=[TranscriptSegment(0, 2000, "test", "asr")],
            source="asr",
            language="en",
        )

    def test_run_uses_subtitle_when_prefer_subtitle_true(self, tmp_path):
        video = tmp_path / "film.mp4"
        video.touch()
        fake = self._fake_transcript()
        fake.source = "subtitle"

        mock_transcriber = MagicMock()
        pipeline = TranscriptionPipeline(transcriber=mock_transcriber, prefer_subtitle=True)
        with patch.object(pipeline.extractor, "find", return_value=fake):
            result = pipeline.run(str(video))

        assert result.source == "subtitle"
        mock_transcriber.transcribe.assert_not_called()

    def test_run_falls_back_to_asr_when_no_subtitle(self, tmp_path):
        video = tmp_path / "film.mp4"
        video.touch()
        fake = self._fake_transcript()

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = fake
        pipeline = TranscriptionPipeline(transcriber=mock_transcriber, prefer_subtitle=True)
        with patch.object(pipeline.extractor, "find", return_value=None):
            result = pipeline.run(str(video))

        mock_transcriber.transcribe.assert_called_once()
        assert result.source == "asr"

    def test_run_skips_subtitle_when_prefer_subtitle_false(self, tmp_path):
        """With prefer_subtitle=False the extractor must not even be consulted."""
        video = tmp_path / "film.mp4"
        video.touch()
        fake = self._fake_transcript()

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = fake
        pipeline = TranscriptionPipeline(transcriber=mock_transcriber, prefer_subtitle=False)

        with patch.object(pipeline.extractor, "find") as mock_find:
            result = pipeline.run(str(video))

        mock_find.assert_not_called()
        mock_transcriber.transcribe.assert_called_once()
        assert result is fake

    def test_run_accepts_string_path(self, tmp_path):
        video = tmp_path / "film.mp4"
        video.touch()
        fake = self._fake_transcript()

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = fake
        pipeline = TranscriptionPipeline(transcriber=mock_transcriber, prefer_subtitle=False)
        result = pipeline.run(str(video))
        assert result is fake

    def test_default_transcriber_is_whisper(self):
        pipeline = TranscriptionPipeline()
        assert isinstance(pipeline.transcriber, WhisperOfflineTranscriber)
