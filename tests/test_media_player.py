"""
Tests for the MediaPlayer subsystem.

Organised in three layers so that adding a player for another platform needs as
little test surgery as possible:

1. Conformance  — parameterised over every concrete implementation found in the
   package. A new player is picked up automatically, with no edit here. This is
   where the *real* contract lives, which is wider than the ABC (see below).
2. Behaviour    — a reusable contract class expressed purely through public ABC
   methods, so any implementation can inherit it by supplying one fixture.
3. MacMediaPlayer specifics — Qt wiring and widget state, which need
   implementation-specific mocking.

Layers 2 and 3 exercise the *real* `MacMediaPlayer`. Qt runs under the
`offscreen` platform plugin (selected in conftest.py), so widgets and signals are
genuine — only the two backend leaves, `QMediaPlayer` and `QAudioOutput`, are
substituted. Playback state lives in Qt's C++ layer and a `QMediaPlayer` with no
media loaded silently ignores `setPosition`, so asserting on real positions would
test nothing; the substitutes are what make the assertions meaningful.
"""

import importlib
import inspect
import pkgutil
from unittest.mock import MagicMock

import pytest

from PySide6.QtMultimedia import QMediaPlayer

import MediaPlayer as player_pkg
from MediaPlayer.MediaPlayer import MediaPlayer
from MediaPlayer.MacMediaPlayer import MacMediaPlayer, _fmt
from MediaPlayer.WindowsMediaPlayer import WindowsMediaPlayer
from MediaPlayer.LinuxMediaPlayer import LinuxMediaPlayer
from MediaPlayer.MediaPlayerFactory import MediaPlayerFactory, MEDIA_PLAYERS


def _all_descendants(cls):
    """
    Every subclass at any depth, not just direct children.

    `cls.__subclasses__()` alone would miss WindowsMediaPlayer and
    LinuxMediaPlayer: both subclass MacMediaPlayer (to reuse its Qt logic
    rather than duplicate ~390 lines twice), so they are grandchildren of
    MediaPlayer, not direct subclasses.
    """
    descendants = []
    for sub in cls.__subclasses__():
        descendants.append(sub)
        descendants.extend(_all_descendants(sub))
    return descendants


def _concrete_players():
    """
    Every concrete MediaPlayer implementation in the package, at any
    inheritance depth.

    Discovered by importing each module under MediaPlayer/, so a player added
    for a new platform is covered by the conformance tests below without this
    file being touched.
    """
    for module in pkgutil.iter_modules(player_pkg.__path__):
        importlib.import_module(f"{player_pkg.__name__}.{module.name}")
    return [cls for cls in _all_descendants(MediaPlayer) if not inspect.isabstract(cls)]


def _instantiate(impl):
    """
    Build `impl` the way main.py does, and return it with a cleanup callable.

    main.py constructs the player as `Player(width=..., height=...)` and nothing
    else, so an implementation that needs more than that cannot be driven by the
    app — `test_constructor_accepts_width_and_height` reports that separately.
    """
    instance = impl(width=200, height=150)

    def cleanup():
        window = getattr(instance, "window", None)
        if window is not None and hasattr(window, "close"):
            window.close()

    return instance, cleanup


CONCRETE_PLAYERS = _concrete_players()

# main.py drives the player through these two signals. They are NOT declared on
# the MediaPlayer ABC, so a player can satisfy all 24 abstract methods, import
# and instantiate cleanly, and still crash main.py at runtime. Pinned here until
# the ABC is widened — see HANDOVER.md defect #7.
REQUIRED_SIGNALS = ("seek_to", "search_requested")


@pytest.fixture
def player(qapp):
    """A real MacMediaPlayer with the Qt multimedia backend mocked out."""
    p = MacMediaPlayer(width=400, height=300)
    p.player = MagicMock()
    p.audio = MagicMock()
    yield p
    p.window.close()


# ---------------------------------------------------------------------------
# 1. Conformance — applies to every implementation, present and future
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("impl", CONCRETE_PLAYERS, ids=lambda c: c.__name__)
class TestMediaPlayerConformance:
    def test_subclasses_the_abc(self, impl):
        assert issubclass(impl, MediaPlayer)

    def test_implements_every_abstract_method(self, impl):
        missing = sorted(
            name for name in MediaPlayer.__abstractmethods__
            if getattr(impl, name, None) is getattr(MediaPlayer, name, None)
        )
        assert not missing, f"{impl.__name__} does not override: {', '.join(missing)}"

    @pytest.mark.parametrize("signal", REQUIRED_SIGNALS)
    def test_exposes_the_signals_main_py_requires(self, impl, signal, qapp):
        """
        main.py calls `player.search_requested.connect(...)` and
        `player.seek_to.emit(...)`. Neither is on the ABC, so nothing else
        catches their absence until the app crashes at runtime.

        Checked on an instance, not the class: Qt's class-level `Signal` object
        has no `connect`/`emit` (only the per-instance `SignalInstance` does),
        and an implementation is equally free to assign its signals in
        `__init__`. What matters is that the attribute is usable on the object
        main.py actually holds.
        """
        try:
            instance, cleanup = _instantiate(impl)
        except Exception as exc:
            pytest.skip(f"cannot instantiate {impl.__name__} generically: {exc}")

        try:
            attr = getattr(instance, signal, None)
            assert attr is not None, (
                f"{impl.__name__} has no `{signal}` — main.py will raise "
                f"AttributeError. See HANDOVER.md defect #7."
            )
            assert callable(getattr(attr, "connect", None)), (
                f"{impl.__name__}.{signal} is not connectable"
            )
            assert callable(getattr(attr, "emit", None)), (
                f"{impl.__name__}.{signal} is not emittable"
            )
        finally:
            cleanup()

    def test_open_accepts_filename_as_a_keyword(self, impl):
        """main.py:101 calls `player.open(filename=filename)`."""
        params = inspect.signature(impl.open).parameters
        assert "filename" in params, (
            f"{impl.__name__}.open() must name its parameter `filename`"
        )

    def test_constructor_accepts_width_and_height(self, impl):
        """main.py:100 constructs the player as Player(width=..., height=...)."""
        params = inspect.signature(impl.__init__).parameters
        assert "width" in params
        assert "height" in params


def test_at_least_one_player_is_discoverable():
    """Guards the discovery helper — an empty list would silently pass everything."""
    assert CONCRETE_PLAYERS, "no concrete MediaPlayer implementations found"


# ---------------------------------------------------------------------------
# 2. Behaviour contract — reusable by any implementation
# ---------------------------------------------------------------------------

class _RecordingBackend:
    """
    Stand-in for QMediaPlayer that actually stores what it is told.

    Deliberately does NOT clamp or validate: clamping is the production code's
    job, so a fake that clamped would hide a missing `max(0, ...)`.
    """

    def __init__(self):
        self._position = 0
        self._duration = 0
        self._rate = 1.0
        self._state = QMediaPlayer.StoppedState

    def setPosition(self, ms): self._position = int(ms)
    def position(self): return self._position
    def duration(self): return self._duration
    def setPlaybackRate(self, r): self._rate = r
    def playbackRate(self): return self._rate
    def playbackState(self): return self._state
    def play(self): self._state = QMediaPlayer.PlayingState
    def pause(self): self._state = QMediaPlayer.PausedState
    def stop(self): self._state = QMediaPlayer.StoppedState
    def setSource(self, url): self._source = url


class MediaPlayerBehaviourContract:
    """
    Behaviour every MediaPlayer must exhibit, asserted only through public ABC
    methods so it is backend-agnostic.

    To cover a new implementation, subclass this and provide a `player` fixture
    returning an instance whose position/duration are observable via
    `current_time()` / `duration()`:

        class TestLinuxPlayerContract(MediaPlayerBehaviourContract):
            @pytest.fixture
            def contract_player(self):
                return LinuxMediaPlayer(width=400, height=300)
    """

    def test_seek_sets_absolute_position(self, contract_player):
        contract_player.seek(5000)
        assert contract_player.current_time() == 5000

    def test_seek_seconds_converts_to_milliseconds(self, contract_player):
        contract_player.seek_seconds(2.5)
        assert contract_player.current_time() == 2500

    def test_seek_seconds_ignores_negative_values(self, contract_player):
        """
        The `-1` sentinel in main.py depends on this: a background thread emits
        seek_to(-1) to mean "nothing found", and the player must not move.
        """
        contract_player.seek(4000)
        contract_player.seek_seconds(-1)
        assert contract_player.current_time() == 4000

    def test_current_seconds_matches_current_time(self, contract_player):
        contract_player.seek(3000)
        assert contract_player.current_seconds() == 3.0

    def test_backward_never_goes_below_zero(self, contract_player):
        contract_player.seek(3000)
        contract_player.backward(10)
        assert contract_player.current_time() == 0

    def test_forward_advances_by_the_given_seconds(self, contract_player):
        contract_player.seek(10_000)
        contract_player.forward(10)
        assert contract_player.current_time() == 20_000

    def test_progress_is_zero_when_duration_is_unknown(self, contract_player):
        assert contract_player.progress() == 0

    def test_playback_speed_round_trips(self, contract_player):
        contract_player.set_playback_speed(1.5)
        assert contract_player.playback_speed() == 1.5


class TestMacMediaPlayerContract(MediaPlayerBehaviourContract):
    """Runs the shared contract against the real MacMediaPlayer."""

    @pytest.fixture
    def contract_player(self, qapp):
        p = MacMediaPlayer(width=400, height=300)
        p.player = _RecordingBackend()
        p.audio = MagicMock()
        yield p
        p.window.close()


class TestWindowsMediaPlayerContract(MediaPlayerBehaviourContract):
    """
    Runs the shared contract against the real WindowsMediaPlayer.

    WindowsMediaPlayer has no code of its own — it subclasses MacMediaPlayer
    verbatim (see WindowsMediaPlayer.py). This class exists so a future edit
    that gives WindowsMediaPlayer real overrides is held to the same contract
    automatically, and so CI's windows-latest runner exercises the real class
    by name, not just its parent.
    """

    @pytest.fixture
    def contract_player(self, qapp):
        p = WindowsMediaPlayer(width=400, height=300)
        p.player = _RecordingBackend()
        p.audio = MagicMock()
        yield p
        p.window.close()


class TestLinuxMediaPlayerContract(MediaPlayerBehaviourContract):
    """Runs the shared contract against the real LinuxMediaPlayer. See TestWindowsMediaPlayerContract."""

    @pytest.fixture
    def contract_player(self, qapp):
        p = LinuxMediaPlayer(width=400, height=300)
        p.player = _RecordingBackend()
        p.audio = MagicMock()
        yield p
        p.window.close()


# ---------------------------------------------------------------------------
# MediaPlayerFactory — platform dispatch
# ---------------------------------------------------------------------------

class TestMediaPlayerFactory:
    @pytest.mark.parametrize("system, expected", [
        ("Darwin", MacMediaPlayer),
        ("Windows", WindowsMediaPlayer),
        ("Linux", LinuxMediaPlayer),
    ])
    def test_dispatches_by_platform_name(self, system, expected):
        assert MediaPlayerFactory.get_media_player(system) is expected

    def test_unrecognised_platform_falls_back_rather_than_raising(self):
        """
        All three registered players are the same Qt implementation, so an
        unknown `platform.system()` string (e.g. "Java" under Jython, or an
        unusual container runtime) should still return something usable —
        mirroring ExploreFactory's fallback for an unrecognised explorer name —
        rather than crash main.py with a KeyError on its very first line.
        """
        assert MediaPlayerFactory.get_media_player("SomeFutureOS") is MacMediaPlayer

    def test_defaults_to_the_real_platform_when_unspecified(self):
        """main.py calls get_media_player() with no argument."""
        cls = MediaPlayerFactory.get_media_player()
        assert cls in MEDIA_PLAYERS.values()

    def test_returns_a_class_not_an_instance(self):
        """main.py calls the result with constructor args: `cls(width=..., height=...)`."""
        assert inspect.isclass(MediaPlayerFactory.get_media_player("Darwin"))


# ---------------------------------------------------------------------------
# 3. MacMediaPlayer specifics
# ---------------------------------------------------------------------------

class TestPlaybackControl:
    def test_play_calls_player_play(self, player):
        player.play()
        player.player.play.assert_called_once()

    def test_pause_calls_player_pause(self, player):
        player.pause()
        player.player.pause.assert_called_once()

    def test_stop_calls_player_stop(self, player):
        player.stop()
        player.player.stop.assert_called_once()

    def test_toggle_pauses_when_playing(self, player):
        player.player.playbackState.return_value = QMediaPlayer.PlayingState
        player.toggle()
        player.player.pause.assert_called_once()
        player.player.play.assert_not_called()

    def test_toggle_plays_when_paused(self, player):
        player.player.playbackState.return_value = QMediaPlayer.PausedState
        player.toggle()
        player.player.play.assert_called_once()
        player.player.pause.assert_not_called()

    def test_open_sets_source(self, player):
        player.open("/tmp/clip.mp4")
        player.player.setSource.assert_called_once()
        url = player.player.setSource.call_args[0][0]
        assert url.toLocalFile() == "/tmp/clip.mp4"


# ---------------------------------------------------------------------------
# Seeking
# ---------------------------------------------------------------------------

class TestSeek:
    def test_seek_sets_position_in_ms(self, player):
        player.seek(5000)
        player.player.setPosition.assert_called_with(5000)

    def test_seek_seconds_converts_to_ms(self, player):
        player.seek_seconds(2.5)
        player.player.setPosition.assert_called_with(2500)

    def test_seek_seconds_ignores_negative(self, player):
        player.seek_seconds(-1)
        player.player.setPosition.assert_not_called()

    def test_seek_seconds_accepts_zero(self, player):
        player.seek_seconds(0)
        player.player.setPosition.assert_called_with(0)

    def test_forward_adds_to_position(self, player):
        player.player.position.return_value = 10_000
        player.forward(10)
        player.player.setPosition.assert_called_with(20_000)

    def test_backward_subtracts_from_position(self, player):
        player.player.position.return_value = 15_000
        player.backward(10)
        player.player.setPosition.assert_called_with(5_000)

    def test_backward_clamps_to_zero(self, player):
        player.player.position.return_value = 3_000
        player.backward(10)
        player.player.setPosition.assert_called_with(0)

    def test_restart_seeks_to_zero_and_plays(self, player):
        player.restart()
        player.player.setPosition.assert_called_with(0)
        player.player.play.assert_called_once()


# ---------------------------------------------------------------------------
# Volume and speed
# ---------------------------------------------------------------------------

class TestVolumeAndSpeed:
    def test_set_volume_delegates(self, player):
        player.set_volume(0.5)
        player.audio.setVolume.assert_called_with(0.5)

    def test_volume_returns_audio_volume(self, player):
        player.audio.volume.return_value = 0.75
        assert player.volume() == 0.75

    def test_set_playback_speed_sets_rate(self, player):
        player.set_playback_speed(1.5)
        player.player.setPlaybackRate.assert_called_with(1.5)

    def test_playback_speed_returns_rate(self, player):
        player.player.playbackRate.return_value = 2.0
        assert player.playback_speed() == 2.0


# ---------------------------------------------------------------------------
# Position and duration
# ---------------------------------------------------------------------------

class TestPositionAndDuration:
    def test_current_time_returns_position(self, player):
        player.player.position.return_value = 3000
        assert player.current_time() == 3000

    def test_current_seconds(self, player):
        player.player.position.return_value = 3000
        assert player.current_seconds() == 3.0

    def test_duration(self, player):
        player.player.duration.return_value = 120_000
        assert player.duration() == 120_000

    def test_duration_seconds(self, player):
        player.player.duration.return_value = 120_000
        assert player.duration_seconds() == 120.0

    def test_progress_correct_percentage(self, player):
        player.player.position.return_value = 30_000
        player.player.duration.return_value = 100_000
        assert player.progress() == 30.0

    def test_progress_zero_when_no_duration(self, player):
        player.player.duration.return_value = 0
        assert player.progress() == 0


# ---------------------------------------------------------------------------
# _fmt — the real module-level helper
# ---------------------------------------------------------------------------

class TestFormatterHelper:
    def test_below_one_hour(self):
        assert _fmt(90_000) == "1:30"

    def test_at_one_hour(self):
        assert _fmt(3_600_000) == "1:00:00"

    def test_zero(self):
        assert _fmt(0) == "0:00"

    def test_pads_seconds_to_two_digits(self):
        assert _fmt(65_000) == "1:05"

    def test_pads_minutes_and_seconds_past_an_hour(self):
        assert _fmt(7_265_000) == "2:01:05"


# ---------------------------------------------------------------------------
# Search UI — real widgets, real signals
# ---------------------------------------------------------------------------

class TestSearchUI:
    def test_on_go_emits_query_stripped(self, player):
        captured = []
        player.search_requested.connect(captured.append)
        player._notes.setPlainText("  explosion scene  ")
        player._on_go()
        assert captured == ["explosion scene"]

    def test_on_go_does_nothing_when_empty(self, player):
        captured = []
        player.search_requested.connect(captured.append)
        player._notes.setPlainText("   ")
        player._on_go()
        assert captured == []

    def test_on_go_leaves_button_enabled_when_empty(self, player):
        player._notes.setPlainText("")
        player._on_go()
        assert player._btn_go.isEnabled() is True

    def test_on_go_disables_button(self, player):
        player._notes.setPlainText("chase scene")
        player._on_go()
        assert player._btn_go.isEnabled() is False

    def test_on_go_changes_button_text(self, player):
        player._notes.setPlainText("opening")
        player._on_go()
        assert player._btn_go.text() == "…"


# ---------------------------------------------------------------------------
# The seek_to signal contract
#
# ARCHITECTURE.md §4: two slots are connected to `seek_to`, and background
# threads emit -1 to mean "nothing found — re-enable the button without
# seeking". Any path that disables the Go button must guarantee an emission,
# so this wiring is what keeps the UI from getting stranded.
# ---------------------------------------------------------------------------

class TestSeekToSignalContract:
    def test_emit_seeks_to_position(self, player):
        player.seek_to.emit(12.5)
        player.player.setPosition.assert_called_with(12_500)

    def test_emit_reenables_go_button(self, player):
        player._notes.setPlainText("something")
        player._on_go()
        assert player._btn_go.isEnabled() is False

        player.seek_to.emit(30)
        assert player._btn_go.isEnabled() is True
        assert player._btn_go.text() == "Go"

    def test_negative_sentinel_resets_button_without_seeking(self, player):
        player._notes.setPlainText("unfindable scene")
        player._on_go()
        assert player._btn_go.isEnabled() is False

        player.seek_to.emit(-1)

        player.player.setPosition.assert_not_called()
        assert player._btn_go.isEnabled() is True
        assert player._btn_go.text() == "Go"
