import platform
from .MacMediaPlayer import MacMediaPlayer
from .WindowsMediaPlayer import WindowsMediaPlayer
from .LinuxMediaPlayer import LinuxMediaPlayer

MEDIA_PLAYERS = {
    "Darwin": MacMediaPlayer,
    "Windows": WindowsMediaPlayer,
    "Linux": LinuxMediaPlayer,
}


class MediaPlayerFactory:

    @classmethod
    def get_media_player(cls, system: str = None):
        """
        `system` defaults to `platform.system()` — pass it explicitly to pick a
        player deterministically (e.g. in tests) without mocking the platform
        module.

        All three registered classes are the same PySide6/Qt6 implementation
        (see WindowsMediaPlayer / LinuxMediaPlayer docstrings), so an
        unrecognised platform string falls back to it rather than raising —
        the same forgiving pattern ExploreFactory uses for an unknown explorer
        name.
        """
        system = system if system is not None else platform.system()
        return MEDIA_PLAYERS.get(system, MacMediaPlayer)