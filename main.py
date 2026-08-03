import sys
import re

from FileExplorer.FileExplorer import FileExplorer
from FileExplorer.ExplorerFactory import ExploreFactory
from Transcribe.Transcriber import TranscriptionPipeline
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


def start_transcribe(filename: str) -> dict:
    pipeline = TranscriptionPipeline()
    result = pipeline.run(filename)
    return result.__dict__

def extract_content(transcribed_data: dict) -> str:
    transcribed_content = []
    for content in transcribed_data.get("segments"):
        transcribed_content.append(content.text)
    
    return " ".join(transcribed_content)

rag: RAG = None

def start_llm_pipeline(filename: str):
    global rag, transcribed_data
    transcribed_data = start_transcribe(filename)
    transcribed_content = extract_content(transcribed_data)
    rag = RAG(db_path=CHROMA_DB_PATH)
    rag.store_to_db(content=transcribed_content)
    print("RAG ready.")

def on_search(query: str):
    """Called (on the main thread via signal) when the user clicks Go."""
    def _run():
        global rag, media_player, transcribed_data
        answer = rag.retrieve_from_db_with_start_timestamp(
            content=query,
            transcribed_data=transcribed_data
        )
        print(f"LLM answer: {answer}")
        seconds = _parse_seconds(answer)
        if seconds is None:
            print("Could not find a timestamp in the LLM response — no seek performed.")
            media_player.seek_to.emit(-1)   # signals Go button to re-enable without seeking
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