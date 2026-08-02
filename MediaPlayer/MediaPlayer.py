from abc import ABC, abstractmethod


class MediaPlayer(ABC):
    """
    Abstract base class for all media player implementations.
    Subclasses must implement every abstract method.
    """

    # ── file ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def open(self, filename: str) -> None:
        """Load a media file from the given path."""

    # ── playback ─────────────────────────────────────────────────────────────

    @abstractmethod
    def play(self) -> None:
        """Start or resume playback."""

    @abstractmethod
    def pause(self) -> None:
        """Pause playback."""

    @abstractmethod
    def stop(self) -> None:
        """Stop playback and reset position to the beginning."""

    @abstractmethod
    def restart(self) -> None:
        """Seek to 0 and start playing."""

    @abstractmethod
    def toggle(self) -> None:
        """Play if paused, pause if playing."""

    # ── seeking ───────────────────────────────────────────────────────────────

    @abstractmethod
    def seek(self, milliseconds: int) -> None:
        """Jump to an absolute position (milliseconds)."""

    @abstractmethod
    def seek_seconds(self, seconds: float) -> None:
        """Jump to an absolute position (seconds)."""

    @abstractmethod
    def forward(self, seconds: float = 10) -> None:
        """Skip forward by the given number of seconds."""

    @abstractmethod
    def backward(self, seconds: float = 10) -> None:
        """Skip backward by the given number of seconds."""

    # ── playback speed ────────────────────────────────────────────────────────

    @abstractmethod
    def set_playback_speed(self, speed: float) -> None:
        """Set playback rate (e.g. 0.5, 1.0, 1.5, 2.0)."""

    @abstractmethod
    def playback_speed(self) -> float:
        """Return the current playback rate."""

    # ── volume ────────────────────────────────────────────────────────────────

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        """Set volume in the range 0.0 (silent) to 1.0 (full)."""

    @abstractmethod
    def volume(self) -> float:
        """Return the current volume (0.0 – 1.0)."""

    # ── position / duration ───────────────────────────────────────────────────

    @abstractmethod
    def current_time(self) -> int:
        """Return the current playback position in milliseconds."""

    @abstractmethod
    def current_seconds(self) -> float:
        """Return the current playback position in seconds."""

    @abstractmethod
    def duration(self) -> int:
        """Return the total duration in milliseconds."""

    @abstractmethod
    def duration_seconds(self) -> float:
        """Return the total duration in seconds."""

    @abstractmethod
    def progress(self) -> float:
        """Return playback progress as a percentage (0 – 100)."""

    # ── window ────────────────────────────────────────────────────────────────

    @abstractmethod
    def show(self) -> None:
        """Make the player window visible."""

    @abstractmethod
    def fullscreen(self) -> None:
        """Switch the window to full-screen mode."""

    @abstractmethod
    def normal_screen(self) -> None:
        """Return the window to its normal (windowed) size."""

    @abstractmethod
    def close(self) -> None:
        """Stop playback and close the player window."""

    # ── event loop ────────────────────────────────────────────────────────────

    @abstractmethod
    def exec(self) -> int:
        """Show the window and run the GUI event loop. Returns the exit code."""
