import sys
import re

from FileExplorer.FileExplorer import FileExplorer
from FileExplorer.ExplorerFactory import ExploreFactory
from Transcribe.Transcriber import TranscriptionPipeline
from Transcribe.VideoChunker import VideoChunker
from MediaPlayer.MediaPlayerFactory import MediaPlayerFactory
import threading
from constants import CHROMA_DB_PATH
from RAGSystem.Rag import RAG


def _parse_seconds(llm_answer: str) -> float | None:
    """
    Try to extract a timestamp from the LLM response.
    Handles: 1:02:30  |  2:30  |  150.5  |  "2 minutes and 30 seconds"
    Returns None if nothing usable is found.
    """
    # HH:MM:SS
    m = re.search(r"(\d+):(\d{2}):(\d{2})", llm_answer)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return h * 3600 + mn * 60 + s

    # MM:SS
    m = re.search(r"(\d+):(\d{2})", llm_answer)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    # "X minutes and Y seconds" / "X min Y sec"
    mins = re.search(r"(\d+)\s*(?:minutes?|mins?)", llm_answer)
    secs = re.search(r"(\d+)\s*(?:seconds?|secs?)", llm_answer)
    if mins or secs:
        return int(mins.group(1) if mins else 0) * 60 + int(secs.group(1) if secs else 0)

    # plain number (last resort)
    m = re.search(r"\d+(?:\.\d+)?", llm_answer)
    if m:
        return float(m.group())

    return None

# Select video
explorer: FileExplorer = ExploreFactory.get_explorer("tk")

explorer_obj = explorer(
    title="Select Video",
    filetypes=[("Videos", "*.mp4 *.mov *.mkv *.avi")]
)

filename = explorer_obj.open()

if not filename:
    sys.exit()


rag: RAG = None
media_player = None

def start_llm_pipeline(filename: str):
    """
    Splits the video into 1-minute audio chunks, transcribes each one, stores
    it in the vector DB immediately, then signals the player to draw a marker.
    The player becomes searchable after the very first chunk is done.
    """
    global rag, media_player
    rag = RAG(db_path=CHROMA_DB_PATH)
    chunker = VideoChunker(chunk_duration=60)
    pipeline = TranscriptionPipeline()

    for chunk_path, start_sec, end_sec in chunker.split_iter(filename):
        try:
            transcript = pipeline.run(chunk_path, time_offset_sec=start_sec)
            if transcript.segments:
                # Store segments with embedded timestamps so the LLM can read them
                lines = [
                    f"[{seg.start_ms // 1000}s] {seg.text}"
                    for seg in transcript.segments
                ]
                rag.store_to_db(content="\n".join(lines))
            if media_player is not None:
                media_player.chunk_ready.emit(start_sec, end_sec)
            print(f"Indexed [{start_sec:.0f}s – {end_sec:.0f}s]")
        except Exception as e:
            print(f"Chunk [{start_sec:.0f}s – {end_sec:.0f}s] failed: {e}")

    print("All chunks indexed — full video searchable.")


def on_search(query: str):
    """Called when the user clicks Go. Runs the RAG query on a background thread."""
    def _run():
        global rag, media_player
        if rag is None:
            print("RAG not ready yet — no chunks indexed.")
            media_player.seek_to.emit(-1)
            return
        answer = rag.retrieve_timestamp_from_context(content=query)
        print(f"LLM answer: {answer}")
        seconds = _parse_seconds(answer)
        if seconds is None:
            print("Could not find a timestamp in the LLM response — no seek performed.")
            media_player.seek_to.emit(-1)
            return
        print(f"Seeking to {seconds}s")
        media_player.seek_to.emit(seconds)

    threading.Thread(target=_run, daemon=True).start()

def play_video(filename: str):
    global media_player
    media_player = MediaPlayerFactory.get_media_player()(width=900, height=600)
    media_player.open(filename=filename)
    media_player.play()
    media_player.search_requested.connect(on_search)
    sys.exit(media_player.exec())


# Transcribe + build RAG index in the background while the video plays
transcribe_thread = threading.Thread(target=start_llm_pipeline, args=(filename,), daemon=True)
transcribe_thread.start()

play_video(filename)