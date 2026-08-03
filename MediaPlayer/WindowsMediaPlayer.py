from MediaPlayer.MacMediaPlayer import MacMediaPlayer


class WindowsMediaPlayer(MacMediaPlayer):
    """
    MacMediaPlayer's implementation is PySide6/Qt6 end to end — nothing in it
    calls a macOS-specific API, so it already runs unmodified on Windows. This
    subclass exists so the platform-detecting factory (MediaPlayerFactory) has
    a distinctly named class per OS, and so any future Windows-only behaviour
    (e.g. taskbar progress) has an obvious place to live.
    """
