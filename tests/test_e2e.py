"""
End-to-end integration tests.

Each test drives one complete user flow through the real module interfaces,
with only external I/O (ffprobe, faster-whisper, Chroma, LLM, Qt) mocked.
"""

import threading
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from Transcribe.Transcriber import (
    Transcript,
    TranscriptSegment,
    TranscriptionPipeline,
)
from RAGSystem.Rag import RAG
from FileExplorer.ExplorerFactory import ExploreFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_transcript(texts=("Hello world", "Goodbye world")):
    segs = [
        TranscriptSegment(i * 2000, (i + 1) * 2000, t, "asr")
        for i, t in enumerate(texts)
    ]
    return Transcript(segments=segs, source="asr", language="en")


def _make_rag(db_path="/tmp/test_db"):
    mock_vdb = MagicMock()
    mock_vdb.from_documents.return_value = mock_vdb
    mock_splitter = MagicMock()
    mock_splitter.create_documents.return_value = [Document(page_content="chunk")]
    return RAG(
        db_path=db_path,
        embedder=MagicMock(),
        splitter=mock_splitter,
        vector_db=mock_vdb,
    )


# ---------------------------------------------------------------------------
# E2E Flow 1 — Subtitle path: existing .srt → skip ASR → build RAG → query
# ---------------------------------------------------------------------------

class TestE2ESubtitleFlow:
    """User opens a video that already has an .srt; ASR is skipped."""

    def test_subtitle_loaded_without_asr(self, tmp_path):
        video = tmp_path / "film.mp4"
        video.touch()
        srt = tmp_path / "film.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nOpening narration\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nThe hero appears\n\n"
        )

        mock_whisper = MagicMock()
        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=True)
        result = pipeline.run(str(video))

        assert result.source == "subtitle"
        assert len(result.segments) == 2
        assert result.segments[0].text == "Opening narration"
        mock_whisper.transcribe.assert_not_called()

    def test_subtitle_content_stored_in_rag(self, tmp_path):
        video = tmp_path / "film.mp4"
        video.touch()
        srt = tmp_path / "film.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello subtitle\n\n")

        pipeline = TranscriptionPipeline(prefer_subtitle=True)
        transcript = pipeline.run(str(video))

        content = " ".join(s.text for s in transcript.segments)

        rag = _make_rag()
        rag.store_to_db(content)
        rag.vector_db.from_documents.assert_called_once()

    def test_rag_query_returns_answer_for_subtitle_content(self, tmp_path):
        video = tmp_path / "film.mp4"
        video.touch()
        srt = tmp_path / "film.srt"
        srt.write_text("1\n00:00:05,000 --> 00:00:07,000\nThe chase scene begins\n\n")

        pipeline = TranscriptionPipeline(prefer_subtitle=True)
        transcript = pipeline.run(str(video))
        content = " ".join(s.text for s in transcript.segments)

        rag = _make_rag()
        rag.store_to_db(content)

        mock_model = MagicMock()
        mock_prompt = MagicMock()
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content="5")
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)

        rag.vector_db.similarity_search.return_value = [Document(page_content="The chase scene")]
        answer = rag.retrieve_from_db_with_start_timestamp(
            content="chase scene",
            transcribed_data=transcript.__dict__,
            model=mock_model,
            prompt=mock_prompt,
        )
        assert answer == "5"


# ---------------------------------------------------------------------------
# E2E Flow 2 — ASR path: no subtitle → WhisperOffline → RAG → timestamp query
# ---------------------------------------------------------------------------

class TestE2EASRFlow:
    """User opens a video with no subtitle; Whisper transcribes it."""

    def test_whisper_called_when_no_subtitle(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.touch()

        fake = _fake_transcript(["Scene one text", "Scene two text"])
        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = fake

        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=True)
        with patch.object(pipeline.extractor, "find", return_value=None):
            result = pipeline.run(str(video))

        mock_whisper.transcribe.assert_called_once()
        assert result.source == "asr"
        assert len(result.segments) == 2

    def test_asr_transcript_stored_and_retrieved(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.touch()

        fake = _fake_transcript(["Opening scene", "The villain laughs"])
        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = fake

        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=True)
        with patch.object(pipeline.extractor, "find", return_value=None):
            transcript = pipeline.run(str(video))

        content = " ".join(s.text for s in transcript.segments)
        rag = _make_rag()
        rag.store_to_db(content)

        mock_model = MagicMock()
        mock_prompt = MagicMock()
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content="2000")
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)
        rag.vector_db.similarity_search.return_value = [Document(page_content="The villain laughs")]

        answer = rag.retrieve_from_db_with_start_timestamp(
            content="villain laughs",
            transcribed_data=transcript.__dict__,
            model=mock_model,
            prompt=mock_prompt,
        )
        assert answer == "2000"

    def test_timestamp_parsed_from_llm_response(self, parse_seconds):
        # LLM returns "The scene starts at 2:00" → _parse_seconds → 120 s
        answer = "The scene starts at 2:00 into the film"
        seconds = parse_seconds(answer)
        assert seconds == 120


# ---------------------------------------------------------------------------
# E2E Flow 3 — Full pipeline: file select → transcribe → store → query → seek
# ---------------------------------------------------------------------------

class TestE2EFullPipeline:
    """Drive the whole pipeline with all external calls mocked."""

    def test_full_pipeline_seek_seconds(self, tmp_path, parse_seconds):
        # 1. File selection
        video = str(tmp_path / "movie.mp4")
        (tmp_path / "movie.mp4").touch()
        explorer_cls = ExploreFactory.get_explorer("tk")
        with patch("FileExplorer.TkinterFileExplorer.Tk"), \
             patch("FileExplorer.TkinterFileExplorer.tkinter.Frame"), \
             patch("FileExplorer.TkinterFileExplorer.filedialog.askopenfilename",
                   return_value=video):
            explorer = explorer_cls(title="Select Video", filetypes=[("Videos", "*.mp4")])
            selected = explorer.open()
        assert selected == video

        # 2. Transcription
        fake = _fake_transcript(["The hero runs", "Explosion happens"])
        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = fake
        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=False)
        transcript = pipeline.run(selected)
        assert len(transcript.segments) == 2

        # 3. Build RAG index
        content = " ".join(s.text for s in transcript.segments)
        rag = _make_rag()
        rag.store_to_db(content)
        rag.vector_db.from_documents.assert_called_once()

        # 4. Query
        mock_model = MagicMock()
        mock_prompt = MagicMock()
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content="The explosion starts at 2:00")
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)
        rag.vector_db.similarity_search.return_value = [Document(page_content="Explosion happens")]

        llm_answer = rag.retrieve_from_db_with_start_timestamp(
            content="explosion",
            transcribed_data=transcript.__dict__,
            model=mock_model,
            prompt=mock_prompt,
        )

        # 5. Parse timestamp
        seek_seconds = parse_seconds(llm_answer)
        assert seek_seconds == 120

    def test_pipeline_handles_llm_no_timestamp(self, tmp_path, parse_seconds):
        """If the LLM cannot find a timestamp, _parse_seconds returns None and no seek occurs."""
        fake = _fake_transcript(["Quiet dinner scene"])
        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = fake
        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=False)
        transcript = pipeline.run(str(tmp_path / "film.mp4"))

        rag = _make_rag()
        mock_model = MagicMock()
        mock_prompt = MagicMock()
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content="I don't know.")
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)
        rag.vector_db.similarity_search.return_value = []

        answer = rag.retrieve_from_db_with_start_timestamp(
            content="dancing scene",
            transcribed_data=transcript.__dict__,
            model=mock_model,
            prompt=mock_prompt,
        )
        assert parse_seconds(answer) is None

    def test_pipeline_runs_transcription_in_background_thread(self, tmp_path):
        """Transcription must not block the calling thread (mirrors main.py's threading.Thread)."""
        fake = _fake_transcript()
        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = fake
        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=False)

        result_holder = {}
        event = threading.Event()

        def background(path):
            result_holder["transcript"] = pipeline.run(path)
            event.set()

        t = threading.Thread(target=background, args=(str(tmp_path / "film.mp4"),), daemon=True)
        t.start()
        finished = event.wait(timeout=5)

        assert finished, "Transcription thread did not complete in time"
        assert result_holder["transcript"].source == "asr"


# ---------------------------------------------------------------------------
# E2E Flow 4 — Edge cases
# ---------------------------------------------------------------------------

class TestE2EEdgeCases:
    def test_bitmap_subtitle_falls_through_to_asr(self, tmp_path):
        video = tmp_path / "dvd_movie.mp4"
        video.touch()

        fake_asr = _fake_transcript(["Dubbed dialogue"])
        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = fake_asr

        # Simulate ffprobe returning only bitmap subtitles
        ffprobe_json = '{"streams": [{"index": 0, "codec_name": "dvd_subtitle"}]}'
        mock_proc = MagicMock()
        mock_proc.stdout = ffprobe_json

        pipeline = TranscriptionPipeline(transcriber=mock_whisper, prefer_subtitle=True)
        with patch("subprocess.run", return_value=mock_proc):
            result = pipeline.run(str(video))

        assert result.source == "asr"
        mock_whisper.transcribe.assert_called_once()

    def test_rag_similarity_search_with_empty_corpus(self):
        rag = _make_rag()
        rag.vector_db.similarity_search.return_value = []
        chunks = rag.similarity_search("anything", k=5)
        assert chunks == []

    def test_transcript_to_json_round_trip(self):
        import json
        original = _fake_transcript(["First line", "Second line"])
        serialised = original.to_json()
        data = json.loads(serialised)
        assert len(data["segments"]) == 2
        assert data["segments"][0]["text"] == "First line"
        assert data["source"] == "asr"
