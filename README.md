# Smart Media Player

> **Platform: macOS, Windows, and Linux.** The player is built entirely on PySide6/Qt6, which
> runs natively on all three — `MediaPlayerFactory` picks the right class for the OS you're on.
> CI runs the full suite on both Linux and Windows runners on every PR.

AI-powered Python video player. Describe any scene in plain English and it jumps straight to that moment. Auto-transcribes with Whisper in the background, uses RAG (ChromaDB + LLM) for scene search. Full playback controls built with PySide6/Qt6. Swap transcription and LLM backends freely.

---

## How it works

1. You pick a video file
2. The player starts immediately
3. In the background, Whisper transcribes the audio and indexes it into ChromaDB
4. Once ready, type any scene description in the search box (e.g. *"the knight's monologue"*) and press **Go**
5. The LLM finds the matching timestamp and the player jumps to it

---

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` installed and on your PATH
- A Groq API key (or any OpenAI-compatible endpoint)

### Install ffmpeg

macOS:
```bash
brew install ffmpeg
```

Windows ([Chocolatey](https://chocolatey.org/)):
```powershell
choco install ffmpeg
```

Linux (Debian/Ubuntu):
```bash
sudo apt install ffmpeg
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/smart-media-player.git
cd smart-media-player
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create a `.env` file

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
MODEL=llama3-8b-8192
BASE_URL=https://api.groq.com/openai/v1
CHROMA_DB_PATH=./chroma_db
```

> You can get a free Groq API key at [console.groq.com](https://console.groq.com).

---

## Run

```bash
python main.py
```

A file picker will open — select any `.mp4`, `.mov`, `.mkv`, or `.avi` file. The player window opens and video starts playing. Transcription runs in the background; the search box becomes usable once indexing is complete (watch the terminal for `RAG ready.`).

---

## Player Controls

| Control | Action |
|---|---|
| ▶ / ⏸ | Play / Pause |
| ⏹ Stop | Stop playback |
| ⏮ 10s / 10s ⏭ | Skip backward / forward 10 seconds |
| Seek bar | Click or drag to any position |
| 🔊 Slider | Adjust volume |
| Speed dropdown | 0.25× – 2.0× playback speed |
| Search box + Go | Describe a scene → jump to it |

---

## Project Structure

```
smart-media-player/
├── main.py                     # Entry point
├── constants.py                # Loads env variables
├── requirements.txt
├── requirements-dev.txt        # + pytest, pytest-mock, pyflakes
├── FileExplorer/
│   ├── FileExplorer.py         # Abstract file picker
│   ├── ExplorerFactory.py      # Factory to get a picker by name
│   └── TkinterFileExplorer.py
├── MediaPlayer/
│   ├── MediaPlayer.py          # Abstract player interface
│   ├── MacMediaPlayer.py       # PySide6/Qt6 implementation
│   ├── WindowsMediaPlayer.py   # Same implementation, run on Windows
│   ├── LinuxMediaPlayer.py     # Same implementation, run on Linux
│   └── MediaPlayerFactory.py   # Picks the right one for platform.system()
├── Transcribe/
│   └── Transcriber.py          # Whisper offline + OpenAI online backends
├── RAGSystem/
│   └── Rag.py                  # ChromaDB + LangChain RAG pipeline
└── tests/                      # pytest suite — see CONTRIBUTING.md
```

`WindowsMediaPlayer` and `LinuxMediaPlayer` are thin subclasses of `MacMediaPlayer` — nothing in
its implementation calls a macOS-specific API, so there was no OS-specific logic to write. The
factory just gives each platform its own class name.

---

## Swapping backends

**Use OpenAI Whisper instead of local Whisper:**

In `main.py`, change:
```python
pipeline = TranscriptionPipeline()
```
to:
```python
from Transcribe.Transcriber import OpenAIOnlineTranscriber
pipeline = TranscriptionPipeline(transcriber=OpenAIOnlineTranscriber())
```

**Use a different LLM:**

Pass a custom `BaseChatModel` to `retrieve_from_db_with_start_timestamp`:
```python
from langchain_openai import ChatOpenAI
model = ChatOpenAI(model="gpt-4o", api_key="...")
rag.retrieve_from_db_with_start_timestamp(content=query, transcribed_data={}, model=model)
```
