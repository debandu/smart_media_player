# Architecture

Technical reference for the Smart Media Player. Covers structure, control flow, the concurrency
model, data shapes, and extension points.

For a shorter orientation read `SUMMARY.md` first. For current defects and work items see
`HANDOVER.md`.

---

## 1. Design goals

The system was built to satisfy five requirements. These came from `PRD.txt`, which was deleted
in commit `7cc0012`; they are recorded here because the whole abstraction strategy below only
makes sense in light of them:

1. Support multiple video container formats.
2. Transcribe video **with timeline information** (not just text).
3. Support multiple LLM backends, both offline and online.
4. Support multiple RAG implementations.
5. Let the user browse and select a file from within the app.

Requirements 2–4 are why almost every subsystem sits behind an abstract base class. The
abstraction is not incidental — it is the primary architectural requirement.

A sixth, implicit goal shapes the runtime design: **the video must start playing immediately**.
Transcribing a feature-length film takes minutes; blocking playback on it would make the app
unusable. This forces the concurrency model described in section 4.

---

## 2. Layer structure

```
┌───────────────────────────────────────────────────────────────────────┐
│                             main.py                                   │
│         entry point · wiring · threading · timestamp parsing          │
└───────────────────────────────────────────────────────────────────────┘
       │                │                  │                  │
       ▼                ▼                  ▼                  ▼
┌────────────┐  ┌──────────────┐  ┌────────────────┐  ┌────────────────┐
│FileExplorer│  │ MediaPlayer  │  │   Transcribe   │  │   RAGSystem    │
├────────────┤  ├──────────────┤  ├────────────────┤  ├────────────────┤
│FileExplorer│  │ MediaPlayer  │  │  Transcriber   │  │      RAG       │
│   (ABC)    │  │    (ABC)     │  │     (ABC)      │  │  (concrete)    │
│     ▲      │  │      ▲       │  │       ▲        │  │                │
│     │      │  │      │       │  │   ┌───┴────┐   │  │                │
│  Tkinter   │  │MacMediaPlayer│  │Whisper  OpenAI │  │                │
│  Explorer  │  │  (PySide6)   │  │Offline  Online │  │                │
│     ▲      │  │      ▲       │  │                │  │                │
│  Explorer  │  │  ┌───┴────┐  │  │ Transcription  │  │                │
│  Factory   │  │Windows Linux │  │   Pipeline     │  │                │
│            │  │(subclass)(") │  │      +         │  │                │
│            │  │      ▲       │  │  Subtitle      │  │                │
│            │  │MediaPlayer   │  │  Extractor     │  │                │
│            │  │  Factory     │  │      +         │  │                │
│            │  │              │  │ VideoChunker   │  │                │
└────────────┘  └──────────────┘  └────────────────┘  └────────────────┘
       │                │                  │                  │
       ▼                ▼                  ▼                  ▼
   tkinter         Qt6 multimedia     ffmpeg/ffprobe      ChromaDB
                    (Win/Linux/Mac)   faster-whisper      HF embeddings
                                      pysubs2             LLM endpoint

                          ┌──────────────┐
                          │ constants.py │  ← .env, imported by RAGSystem + main
                          └──────────────┘
```

Dependencies point downward and inward only. No subsystem imports another subsystem;
`main.py` is the sole integration point. This keeps each package independently testable, which
is what makes the test suite possible without a display or API keys.

---

## 3. Components

### 3.1 `constants.py`

Loads `.env` via `python-dotenv` at import time and exposes four module-level constants:
`GROQ_API_KEY`, `MODEL`, `BASE_URL`, `CHROMA_DB_PATH`.

Values are read **once at import**. There is no validation — a missing `.env` yields `None`
for every constant, and the failure surfaces much later as a confusing error from the LLM
client or Chroma.

`RAGSystem/Rag.py` imports these with `from constants import *`.

### 3.2 `FileExplorer/` — file selection

| File | Role |
|---|---|
| `FileExplorer.py` | ABC declaring `open()` and `close()`, plus `title` / `filetypes` attributes. |
| `TkinterFileExplorer.py` | Tkinter implementation. Constructs a `Tk()` root, then `open()` shows `filedialog.askopenfilename` and returns the path (empty string if cancelled). |
| `ExplorerFactory.py` | `get_explorer(name)` returns the **class** (not an instance) for a given key. `"tk"` → `TkinterFileExplorer`; anything else falls back to the same. |

**Pattern:** Abstract Base Class + Factory. The factory returning a class rather than an
instance is deliberate — the caller supplies constructor arguments (`title`, `filetypes`).

**Note:** the Tk root window is created in `__init__` and never destroyed, so a Tk event loop
lingers alongside Qt for the process lifetime.

### 3.3 `MediaPlayer/` — playback and UI

| File | Role |
|---|---|
| `MediaPlayer.py` | ABC defining the complete player contract: file, playback, seeking, speed, volume, position/duration, window, event loop. 24 abstract methods. |
| `MacMediaPlayer.py` | PySide6/Qt6 implementation. Owns the entire GUI. |
| `WindowsMediaPlayer.py` | `class WindowsMediaPlayer(MacMediaPlayer): pass` — no code of its own. |
| `LinuxMediaPlayer.py` | `class LinuxMediaPlayer(MacMediaPlayer): pass` — same. |
| `MediaPlayerFactory.py` | `get_media_player(system=None)` returns the class for `system` (default `platform.system()`). Unrecognised values fall back to `MacMediaPlayer`, the same forgiving pattern `ExploreFactory` uses. |

**Why Windows and Linux are one-line subclasses, not separate implementations:** nothing in
`MacMediaPlayer` calls a macOS-specific API — it is PySide6/Qt6 end to end, which already runs
identically on all three desktop platforms. Writing out three copies of the ~390-line
implementation would triple the maintenance surface for zero behavioural gain. The subclasses
exist so the factory has a distinctly named class per OS, and so any *genuinely* OS-specific
behaviour added later (taskbar integration, desktop-file association, …) has an obvious,
namespaced place to live — they are extension points, not filler.

`MacMediaPlayer` is both a `QObject` (so it can declare Qt signals) and a `MediaPlayer` (so it
satisfies the ABC). Those two base classes have incompatible metaclasses — Qt's Shiboken
metaclass and `ABCMeta` — so the module defines a merged metaclass to resolve the conflict:

```python
class _Meta(type(QObject), ABCMeta):
    """Resolves the metaclass conflict between QObject (Shiboken) and ABCMeta."""

class MacMediaPlayer(QObject, MediaPlayer, metaclass=_Meta):
```

This is load-bearing and has a direct consequence for testing: the class body cannot be
executed when Qt is mocked, because `type(QObject)` on a `MagicMock` is not a valid metaclass.
See section 7.

**UI construction** is decomposed into focused builders called from `__init__`, in order:
`_build_video` → `_build_seek_bar` → `_build_controls` → `_build_notes` → `_build_player`.
`_build_player` is last because it creates the Qt backend and wires every signal.

**Three custom pieces of UI behaviour:**

- `_ClickSlider` — a `QSlider` subclass that jumps to the clicked position instead of performing
  a page step. Used for both the seek bar and the volume slider. The seek-bar instance also owns
  the RAG-progress overlay: `add_marker(start_ms, end_ms)` appends an indexed region, and a
  custom `paintEvent` paints grey (`#888888`) segments on the track groove after `super()` draws
  the green played portion, starting exactly at the handle's right edge so the circle is never
  obscured. Handle position is computed as `(value / maximum) × (width − 12) + 12` to match
  Qt's own positioning formula for a 12 px handle.
- `_fmt(ms)` — formats milliseconds as `M:SS`, widening to `H:MM:SS` only past an hour.

**Three custom signals** form the entire cross-thread contract:

| Signal | Direction | Purpose |
|---|---|---|
| `search_requested(str)` | player → app | User pressed **Go**. Carries the query text. |
| `seek_to(float)` | app → player | Seek to N seconds. Safe to emit from any thread. |
| `chunk_ready(float, float)` | app → player | A chunk spanning `(start_sec, end_sec)` has been indexed. Safe to emit from the transcription thread. |

All three are declared on `MacMediaPlayer`, **not** on the `MediaPlayer` ABC — so they are part of the
real contract without being part of the enforced one. `WindowsMediaPlayer` and `LinuxMediaPlayer`
inherit them safely *because* they subclass `MacMediaPlayer` rather than `MediaPlayer` directly;
a future implementation that doesn't would hit the exact gap described in `HANDOVER.md` defect
#7, which stays open for that reason. See §6 before writing a genuinely independent
implementation (a different toolkit, not another desktop OS).

### 3.4 `Transcribe/` — getting text with timestamps

The subsystem spans two files.

**`VideoChunker.py`** — splits a video into fixed-duration audio-only WAV chunks before
transcription. Uses `ffprobe` to get the total duration, then loops through 1-minute windows,
extracting each as a 16 kHz mono WAV with `ffmpeg`. The key design is a **lazy generator**:

```python
for chunk_path, start_sec, end_sec in chunker.split_iter(video_path):
    # one chunk is on disk here; the next is not extracted yet
```

Each chunk is extracted, yielded, and then deleted immediately after the caller's loop body
completes — so at most one chunk file lives on disk at a time. This keeps peak disk usage to
~2 MB regardless of video length.

**`Transcriber.py`** — four concerns in one module:

**Data model**

```python
@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms:   int
    text:     str
    source:   Literal["subtitle", "asr"]

@dataclass
class Transcript:
    segments: list[TranscriptSegment]
    source:   Literal["subtitle", "asr"] = "asr"
    language: Optional[str] = None
```

**`SubtitleExtractor`** — tries to avoid ASR entirely, via a three-step waterfall:

1. **Sidecar file** — look for `<video>.srt` / `.vtt` / `.ass` / `.ssa` / `.sub` next to the video.
2. **Embedded stream** — run `ffprobe` to list subtitle streams; if a text-based one exists,
   extract it to `.srt` with `ffmpeg`.
3. **Give up** — return `None` so the pipeline falls through to ASR.

Bitmap subtitle codecs (`hdmv_pgs_subtitle`, `dvd_subtitle`, `dvb_subtitle`) are explicitly
skipped: they are images, and extracting them would require OCR. Falling back to ASR is
cheaper and more reliable than adding an OCR dependency.

`ffprobe` failures (`CalledProcessError`, `FileNotFoundError` — i.e. ffmpeg not installed) are
swallowed and treated as "no subtitle found", so a missing ffmpeg degrades to ASR rather than
crashing.

**`Transcriber` (ABC) + implementations** — the Strategy pattern, satisfying PRD requirement 3:

- `WhisperOfflineTranscriber` — local `faster-whisper`. Default: `base` model, CPU, `int8`.
- `OpenAIOnlineTranscriber` — hosted Whisper via the OpenAI API.

Both import their heavy dependency **lazily inside `transcribe()`**, so neither
`faster-whisper` nor `openai` needs to be importable unless actually used.

**`TranscriptionPipeline`** — the orchestrator, and the only class callers need:

```python
def run(self, video_path, time_offset_sec: float = 0.0) -> Transcript:
    if self.prefer_subtitle:
        existing = self.extractor.find(video_path)
        if existing:
            return existing          # fast path — no ASR
    return self.transcriber.transcribe(video_path, time_offset_sec=time_offset_sec)
```

`time_offset_sec` is the chunk's absolute start position in the original video. Both ASR
implementations shift every `start_ms`/`end_ms` by `offset_ms = int(time_offset_sec * 1000)`,
so the `Transcript` returned always carries **absolute** timestamps regardless of which chunk
produced it.

Both the transcriber and the subtitle preference are constructor-injected, which is what makes
this subsystem trivially testable.

### 3.5 `RAGSystem/Rag.py` — retrieval

A single `RAG` class with fully injectable dependencies (splitter, embedder, vector store,
model, prompt), each defaulting to a sensible concrete choice if omitted.

**Indexing** — `store_to_db(content)`:

```
raw transcript text
  → RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=50)
  → HuggingFaceEmbeddings("all-MiniLM-L6-v2")
  → Chroma(persist_directory=CHROMA_DB_PATH)
```

**Stored format** — segments are stored with embedded timestamps so retrieved chunks are
self-describing:

```
[0s] Welcome to the show.
[4s] Today we cover three topics.
[61s] Moving on to the second topic…
```

`main.py` formats each `TranscriptSegment` as `[{start_ms // 1000}s] {text}` before passing it
to `store_to_db`. The splitter operates on this formatted string, so timestamp markers appear
in whatever chunks the splitter produces.

**Retrieval** — three methods sharing the same shape (`similarity_search(k=10)` → join chunks
into a context string → `prompt | model` LCEL chain → return `.content`):

| Method | Prompt asks for | Used by |
|---|---|---|
| `retrieve_from_db` | A factual answer, or "I don't know." | Not currently wired into the app |
| `retrieve_timestamp_from_context` | **A start timestamp in seconds**, read from `[Xs]` markers in the retrieved context | The Go button |
| `retrieve_from_db_with_start_timestamp` | A start timestamp, but by correlating against a passed-in full transcript dict | Legacy — no longer called by `main.py` |

`retrieve_timestamp_from_context` is the active method. It avoids sending the full transcript
in every prompt (the main weakness of the old approach) by relying on timestamps embedded in
the indexed text. The LLM reads the `[Xs]` prefix from the most-relevant retrieved chunk and
returns that number directly.

### 3.6 `main.py` — composition root

Five responsibilities:

1. `_parse_seconds(llm_answer)` — coerce free-form LLM output into a number of seconds.
2. Select the video file at module scope.
3. `start_llm_pipeline` — split video into chunks; transcribe, store, and signal each one.
4. `on_search` — handle a search request.
5. `play_video` — construct the player, connect signals, enter the Qt event loop.

**`start_llm_pipeline` now processes chunks incrementally.** For each 1-minute chunk from
`VideoChunker.split_iter`:

1. Transcribe the chunk via `TranscriptionPipeline.run(chunk_path, time_offset_sec=start_sec)`.
2. Format segments as `[Xs] text` and call `rag.store_to_db`.
3. Emit `media_player.chunk_ready(start_sec, end_sec)` so the seek bar gains a green marker.
4. Delete the chunk WAV (handled by the generator).

The player is searchable after the **first** chunk — roughly 60 s after playback starts —
rather than after the entire video is transcribed.

**`_parse_seconds` matters more than its size suggests.** The LLM is asked for "seconds" but in
practice returns anything from `150` to `"about 2 minutes and 30 seconds in"`. The function
tries four patterns in descending specificity and returns `None` if none match:

| Order | Pattern | Example | Result |
|---|---|---|---|
| 1 | `HH:MM:SS` | `1:02:30` | 3750 |
| 2 | `MM:SS` | `2:30` | 150 |
| 3 | `N minutes` / `N seconds` | `2 minutes and 30 seconds` | 150 |
| 4 | Any bare number | `150.5` | 150.5 |

Order is significant: `HH:MM:SS` must be tried before `MM:SS` (the `MM:SS` regex would
otherwise match the first two fields of a `HH:MM:SS` string), and the natural-language patterns
must precede the bare-number fallback (which would otherwise grab just the `2` from
"2 minutes 30 seconds"). Both orderings are locked in by `tests/test_parse_seconds.py`.

Returning `None` is a real outcome, not just an error path — it drives the "no seek performed"
branch described in section 4.

---

## 4. Concurrency model

The most important section in this document. Three threads participate.

```
MAIN THREAD (Qt event loop)              BACKGROUND THREADS
──────────────────────────────           ─────────────────────────────────────

pick file
   │
   ├──── spawn ─────────────────────────▶ [transcription thread]  (daemon)
   │                                          rag = RAG(...)
   │                                          for chunk, start, end in VideoChunker:
   │                                            ffmpeg extracts 1-min WAV
   │                                            pipeline.run(chunk, time_offset=start)
   │                                            rag.store_to_db(timestamped text)
   │                                            chunk_ready.emit(start, end)  ──────┐
   │                                            WAV deleted                         │
   │                                          [repeat for every minute]             │
   │                                          ── thread exits ──                    │
   ▼                                                                                │
MacMediaPlayer()                                                                    │
player.open() / play()                  ◀── Qt queues chunk_ready to main thread ──┘
search_requested.connect(on_search)
chunk_ready.connect(_on_chunk_ready)
   │  ← _on_chunk_ready fires here, adds green marker to seek bar
   │
media_player.exec()   ← blocks here for the rest of the process lifetime
   │
   │  user types a query, clicks Go
   │  _on_go(): disable button, set text "…"
   │  emit search_requested(query)
   │       │
   │       └──▶ on_search(query)
   │                └──── spawn ────────▶ [search thread]  (daemon, one per search)
   │                                          if rag is None: emit(-1); return
   │                                          rag.retrieve_timestamp_from_context()
   │                                            vector search + LLM call  (slow, blocking)
   │                                          _parse_seconds(answer)
   │                                          seek_to.emit(seconds)   ── or emit(-1)
   │                                          ── thread exits ──
   │                                                   │
   │   ◀─── Qt queues the signal to the main thread ───┘
   │
   ├─ seek_seconds(seconds)   → player jumps
   └─ _on_seek_done()         → re-enable Go button
```

### Why threads at all

Both transcription and LLM inference are slow and blocking. Running either on the Qt main
thread would freeze the UI — no repaints, no playback controls, a spinning cursor. Both are
therefore pushed to daemon threads so the event loop stays responsive.

Daemon threads are used so that closing the player window terminates the process immediately
rather than waiting on an in-flight transcription.

### How results get back safely

Qt widgets may only be touched from the thread that created them. A background thread cannot
call `player.setPosition()` directly. The solution is a Qt signal:

```python
self.seek_to.connect(self.seek_seconds)    # do the seek
self.seek_to.connect(self._on_seek_done)   # re-enable the Go button
```

`seek_to.emit(x)` is safe from any thread — Qt automatically queues the delivery onto the
main thread, where both slots then run. This is the single mechanism keeping the app
thread-safe, and any new background work must use the same pattern.

### The `-1` sentinel

Note that **two** slots are connected to `seek_to`. That is what makes this work:

```python
seconds = _parse_seconds(answer)
if seconds is None:
    media_player.seek_to.emit(-1)   # re-enable Go without seeking
    return
media_player.seek_to.emit(seconds)
```

When the LLM returns no usable timestamp, the code emits `-1`. `seek_seconds` guards against
negatives and returns early, so no seek happens — but `_on_seek_done` still fires, restoring the
Go button. One signal, two slots, and a sentinel value serve as both "seek here" and
"nothing found, reset the UI".

It is compact but non-obvious. **Any code path that disables the Go button must guarantee a
`seek_to` emission**, or the button is stuck disabled forever. This is exactly the failure mode
of known bug #1 in `HANDOVER.md`.

### Shared state

`main.py` coordinates threads through two module-level globals: `rag` and `media_player`.
There are no locks. Safety currently rests on an assumption rather than enforcement: the
transcription thread only writes `rag`, search threads only read it, and `chunk_ready` emissions
are delivered safely via Qt's signal queue. The `rag is None` guard in `on_search` handles the
narrow window before the first chunk is indexed.

---

## 5. Data flow and shapes

Tracing a single search from click to seek, with the concrete type at each hop:

```
"the explosion scene"                       str
  │ search_requested signal
  ▼
rag.retrieve_timestamp_from_context(content=...)
  │
  ├─ similarity_search(k=10)               list[Document]
  ├─ "\n".join(c.page_content)             str   (context, contains "[Xs] text" lines)
  ├─ prompt | model  → invoke              AIMessage
  ▼
"120"                                       str   (.content)
  │ _parse_seconds
  ▼
120.0                                       float | None
  │ seek_to.emit  (thread hop → main thread)
  ▼
player.setPosition(120000)                  int   (milliseconds)
```

Timestamps flow from `TranscriptSegment.start_ms` → embedded text `[Xs]` → stored document →
retrieved context → LLM response → `_parse_seconds` → `seek_to.emit` → `setPosition`. They are
never lost because each segment's absolute time is encoded into the stored string at index time.

### Units

Milliseconds and seconds are both in play. The boundary is precise:

| Layer | Unit |
|---|---|
| `TranscriptSegment.start_ms` / `end_ms` | milliseconds |
| Qt `QMediaPlayer` position/duration | milliseconds |
| LLM prompt and response | **seconds** |
| `_parse_seconds` return | **seconds** |
| `seek_to` signal payload | **seconds** |
| `seek_seconds()` → `seek()` | converts seconds → ms |

`seek_seconds` is the single conversion point. Keep it that way.

---

## 6. Patterns and extension points

| Pattern | Where | Why |
|---|---|---|
| Abstract Base Class | `FileExplorer`, `MediaPlayer`, `Transcriber` | PRD requires swappable implementations |
| Factory | `ExploreFactory` | Select a picker by string key |
| Strategy | `Transcriber` subclasses | Swap ASR backend without touching the pipeline |
| Facade | `TranscriptionPipeline`, `RAG` | Hide multi-step internals behind one call |
| Dependency injection | `RAG.__init__`, `TranscriptionPipeline.__init__` | Testability and runtime substitution |
| Lazy import | `faster_whisper`, `openai` | Optional heavy dependencies |
| Signal/slot | `seek_to`, `search_requested` | Thread-safe cross-boundary communication |

### Adding a transcription backend

Subclass `Transcriber`, implement `transcribe(video_path, time_offset_sec=0.0) -> Transcript`,
apply the offset to every segment's `start_ms`/`end_ms`, and import the heavy dependency lazily
inside the method:

```python
class MyTranscriber(Transcriber):
    def transcribe(self, video_path: Path, time_offset_sec: float = 0.0) -> Transcript:
        import my_asr_library          # lazy — only loaded when actually called
        offset_ms = int(time_offset_sec * 1000)
        raw = my_asr_library.transcribe(str(video_path))
        segments = [
            TranscriptSegment(
                start_ms=int(s.start * 1000) + offset_ms,
                end_ms=int(s.end * 1000) + offset_ms,
                text=s.text.strip(),
                source="asr",
            )
            for s in raw
        ]
        return Transcript(segments=segments, source="asr")

pipeline = TranscriptionPipeline(transcriber=MyTranscriber())
```

Nothing else changes. `time_offset_sec` is always passed by `TranscriptionPipeline.run()` —
the default of `0.0` means a backend that ignores it will work correctly for full-video
transcription but produce wrong timestamps when used with the chunked pipeline.

### Adding a file explorer

**First check whether you need one.** Nothing in `FileExplorer/` is macOS-specific — Tkinter's
`filedialog` already runs on Windows and Linux. A second implementation is worth adding for
*look and feel* (Qt's `QFileDialog` gives a native dialog on each platform, and PySide6 is
already a dependency), not for functionality.

Subclass `FileExplorer`, implement `open()` and `close()` — **both taking `self`** — accept
`title` and `filetypes` in `__init__`, and register the key in `ExploreFactory.get_explorer`.

`tests/test_explorer.py` discovers concrete implementations by walking the package, so a new
explorer is automatically covered by the conformance suite (ABC compliance, method signatures,
constructor shape) with no test edits. Implementation-specific behaviour still needs its own
test class, because the mocking differs per backend.

**If you make the factory resolve by platform**, keep `get_explorer("tk")` returning
`TkinterFileExplorer` — the tests treat that explicit key as a stable contract, while
deliberately not asserting which class an *unknown* key returns. `MediaPlayerFactory` already
does exactly this for the player (see §3.3): explicit keys are stable, an unrecognised platform
string falls back rather than raising.

### Adding a player

Windows and Linux are already covered — `WindowsMediaPlayer` and `LinuxMediaPlayer` are one-line
subclasses of `MacMediaPlayer`, registered in `MediaPlayerFactory`, and CI proves them for real
on `ubuntu-latest` and `windows-latest` runners on every PR. **Before writing a fourth
implementation, confirm you actually need one** — the only reason to add a new class is either a
different windowing toolkit entirely, or OS-specific behaviour layered on top of one of the
three subclasses above (that's exactly what they're there for; see §3.3).

If you do add a genuinely new implementation, the real contract is **wider than the ABC**:

| Requirement | Declared on the ABC? | Where it's actually used |
|---|---|---|
| 24 abstract methods | Yes | throughout |
| `seek_to` signal — connectable + emittable | **No** | `main.py` — `on_search` |
| `search_requested` signal — connectable + emittable | **No** | `main.py` — `play_video` |
| `chunk_ready` signal — connectable + emittable | **No** | `main.py` — `start_llm_pipeline` |
| `open()`'s parameter named `filename` | No (name not enforced) | `main.py` — `play_video` |
| `__init__` accepting `width` / `height` | No | `main.py` — `play_video` |

A player that overrides all 24 methods but omits `search_requested` instantiates cleanly, plays
video correctly, and silently never runs a scene search. That is `HANDOVER.md` defect #7 — widen
the ABC when you get the chance.

The signals must be exposed on the **instance** and expose `connect`/`emit`. Declaring them as
class-level Qt `Signal` objects satisfies this (Qt turns them into per-instance `SignalInstance`
objects), but so does assigning your own signal objects in `__init__` — the contract is
duck-typed, not Qt-bound.

`tests/test_media_player.py` discovers concrete implementations by walking the package, so a new
player is automatically covered by the conformance suite (ABC completeness, both signals, the
`filename` keyword, constructor shape) with no test edits.

For behavioural coverage, inherit the shared contract and supply one fixture — exactly what
`TestWindowsMediaPlayerContract` and `TestLinuxMediaPlayerContract` already do:

```python
class TestWindowsMediaPlayerContract(MediaPlayerBehaviourContract):
    @pytest.fixture
    def contract_player(self, qapp):
        p = WindowsMediaPlayer(width=400, height=300)
        p.player = _RecordingBackend()
        p.audio = MagicMock()
        yield p
        p.window.close()
```

That contract is written purely against public ABC methods — seek/clamp arithmetic, unit
conversion, and the negative-seek rejection that the `-1` sentinel in §4 depends on — so it
applies to any backend, Qt or otherwise.

One discovery detail worth knowing if you subclass a subclass (as Windows/Linux do):
`test_media_player.py`'s discovery walks the **entire** subclass tree recursively, not just
`MediaPlayer.__subclasses__()`. A single-level walk would miss `WindowsMediaPlayer` and
`LinuxMediaPlayer` entirely, since they are grandchildren of `MediaPlayer` — an early version of
this suite had exactly that bug (confirmed by mutation: a broken `open()` signature on
`WindowsMediaPlayer` produced zero failures until the walk was made recursive).

### Swapping the LLM or vector store

Both are injectable per call or per instance:

```python
rag = RAG(db_path=..., vector_db=MyVectorStore(), embedder=MyEmbeddings())
rag.retrieve_from_db_with_start_timestamp(content=q, transcribed_data=t, model=ChatAnthropic(...))
```

---

## 7. Testability constraints

Two architectural facts make this project awkward to test (`tests/`, 163 tests). Both are worked
around in `tests/conftest.py` **without duplicating production logic** — a distinction that
matters, and that an earlier version of this suite got wrong.

**`main.py` runs on import.** File selection, thread creation, and the Qt event loop all execute
at module scope, so `import main` opens a dialog and hangs. The workaround is to parse the source
with `ast`, pull out just the `_parse_seconds` function node, and compile it in isolation:

```python
tree = ast.parse(source_path.read_text())
func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
module = ast.Module(body=[ast.Import(names=[ast.alias(name="re")]), func], type_ignores=[])
exec(compile(module, str(source_path), "exec"), namespace)
```

The tests therefore run against the **real** function object. Edit `_parse_seconds` and the
tests pick the change up automatically; delete it and the fixture raises a clear error. This
becomes unnecessary once `main.py` is refactored behind an `if __name__ == "__main__":` guard.

**Qt needs a display.** The `_Meta` metaclass evaluates `type(QObject)` at class-definition
time, so substituting a `MagicMock` for `QObject` raises
`TypeError: ABCMeta.__new__() missing 3 required positional arguments` — mocking Qt at
`sys.modules` level cannot work, because the failure happens in the class body itself.

The solution is not to mock Qt but to run it headless. `conftest.py` sets
`QT_QPA_PLATFORM=offscreen` before PySide6 is imported, and a session-scoped `qapp` fixture
provides the single permitted `QApplication`. Tests then construct a **real** `MacMediaPlayer`
and replace only the two backend leaves:

```python
p = MacMediaPlayer(width=400, height=300)
p.player = MagicMock()   # QMediaPlayer
p.audio  = MagicMock()   # QAudioOutput
```

Real widgets, real signals, real production methods; the mocks capture what the code asked Qt
to do. That split is necessary rather than stylistic: playback state lives in Qt's C++ layer,
and a `QMediaPlayer` with no media loaded silently ignores `setPosition`, so asserting on real
positions would assert nothing. Asserting on the mocked call is what actually pins the
behaviour down.

This also makes the `seek_to` signal contract from §4 directly testable — `seek_to.emit(-1)`
can be verified to reset the Go button without seeking, which is the invariant the whole
threading design rests on.

Everything else — subtitle extraction, the transcription pipeline, RAG, the factory, and all
end-to-end flows — is tested against the real classes with only external I/O mocked
(`subprocess`, Whisper, Chroma, the LLM, `tkinter`).

### Verifying the tests actually test something

The suite has been checked with mutation testing: 26 deliberate defects were injected into the
production code (inverted conditions, removed guards, wrong unit conversions, unwired signals)
and **all 26 caused test failures**. Re-run that check after significant test changes — a
passing suite is not by itself evidence of coverage. An earlier version of this suite passed
all 98 of its tests while `_parse_seconds` and `MacMediaPlayer` could be broken arbitrarily
without a single failure, because those tests asserted against hand-written copies rather than
the real code.
