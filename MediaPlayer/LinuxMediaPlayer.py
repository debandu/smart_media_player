from MediaPlayer.MacMediaPlayer import MacMediaPlayer


class LinuxMediaPlayer(MacMediaPlayer):
    """
    MacMediaPlayer's implementation is PySide6/Qt6 end to end — nothing in it
    calls a macOS-specific API, so it already runs unmodified on Linux. This
    subclass exists so the platform-detecting factory (MediaPlayerFactory) has
    a distinctly named class per OS, and so any future Linux-only behaviour
    (e.g. desktop-file / MPRIS integration) has an obvious place to live.
    """
