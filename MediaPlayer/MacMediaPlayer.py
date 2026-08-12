import sys

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QComboBox,
    QTextEdit,
    QSizePolicy,
)
from PySide6.QtCore import QUrl, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from MediaPlayer.MediaPlayer import MediaPlayer
from abc import ABCMeta


class _Meta(type(QObject), ABCMeta):
    """Resolves the metaclass conflict between QObject (Shiboken) and ABCMeta."""


def _fmt(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


class _ClickSlider(QSlider):
    """QSlider that jumps to the clicked position and paints grey RAG-indexed segments."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._markers: list[tuple[int, int]] = []  # (start_ms, end_ms)

    def add_marker(self, start_ms: int, end_ms: int):
        self._markers.append((start_ms, end_ms))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = int(
                event.position().x() / self.width()
                * (self.maximum() - self.minimum())
                + self.minimum()
            )
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._markers or self.maximum() == 0:
            return
        painter = QPainter(self)
        track_h = 4
        track_y = self.height() // 2 - track_h // 2
        w = self.width()
        handle_w = 12  # must match QSlider::handle width in _SLIDER_STYLE
        # Qt positions the handle so its left edge travels over (w - handle_w) pixels
        handle_right = int(self.value() / self.maximum() * (w - handle_w)) + handle_w
        for start_ms, end_ms in self._markers:
            x1 = int(start_ms / self.maximum() * w)
            x2 = int(end_ms / self.maximum() * w)
            draw_from = max(x1, handle_right)
            draw_to = min(x2, w)
            if draw_to > draw_from:
                painter.fillRect(draw_from, track_y, draw_to - draw_from, track_h, QColor("#888888"))
        painter.end()


_SLIDER_STYLE = (
    "QSlider::groove:horizontal{height:4px;background:#444;border-radius:2px;}"
    "QSlider::sub-page:horizontal{background:#1db954;border-radius:2px;}"
    "QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;"
    "background:#fff;border-radius:6px;}"
)

_BTN_STYLE = (
    "QPushButton{background:#333;color:#fff;border:none;border-radius:4px;"
    "padding:4px 10px;font-size:13px;}"
    "QPushButton:hover{background:#555;}"
    "QPushButton:pressed{background:#222;}"
)


class MacMediaPlayer(QObject, MediaPlayer, metaclass=_Meta):

    seek_to = Signal(float)          # emit from any thread; Qt delivers it on the main thread
    search_requested = Signal(str)   # emitted when the user clicks Go
    chunk_ready = Signal(float, float)  # (start_sec, end_sec) — emitted after each chunk is indexed

    def __init__(self, width=900, height=680, title="Video Player"):
        QObject.__init__(self)
        self.app = QApplication.instance() or QApplication(sys.argv)

        self.window = QWidget()
        self.window.setWindowTitle(title)
        self.window.resize(width, height)
        self.window.setStyleSheet("background-color:#1e1e1e;color:#ffffff;")

        self._root = QVBoxLayout(self.window)
        self._root.setContentsMargins(8, 8, 8, 8)
        self._root.setSpacing(6)

        self._build_video()
        self._build_seek_bar()
        self._build_controls()
        self._build_notes()
        self._build_player()

    # ── widget builders ───────────────────────────────────────────────────────

    def _build_video(self):
        """Video display area that expands to fill available space."""
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._root.addWidget(self.video_widget)

    def _build_seek_bar(self):
        """Seek slider with elapsed / total time labels; grey segments mark RAG-indexed regions."""
        row = QHBoxLayout()

        self._time_label = QLabel("0:00")
        self._time_label.setFixedWidth(44)
        self._time_label.setStyleSheet("color:#aaa;font-size:12px;")

        self._seek = _ClickSlider(Qt.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.setStyleSheet(_SLIDER_STYLE)
        self._seek.sliderMoved.connect(self._on_seek)

        self._dur_label = QLabel("0:00")
        self._dur_label.setFixedWidth(44)
        self._dur_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._dur_label.setStyleSheet("color:#aaa;font-size:12px;")

        row.addWidget(self._time_label)
        row.addWidget(self._seek)
        row.addWidget(self._dur_label)
        self._root.addLayout(row)

    def _build_controls(self):
        """Row containing: skip-back, play/pause, stop, skip-forward, volume, speed."""
        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(self._build_skip_buttons())
        row.addStretch()
        row.addLayout(self._build_volume_control())
        row.addSpacing(12)
        row.addLayout(self._build_speed_control())

        self._root.addLayout(row)

    def _build_skip_buttons(self):
        """⏮ 10s  ▶/⏸  ⏹  10s ⏭ — grouped in their own widget."""
        group = QWidget()
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._btn_backward = QPushButton("⏮ 10s")
        self._btn_backward.setStyleSheet(_BTN_STYLE)
        self._btn_backward.clicked.connect(lambda: self.backward(10))

        self._btn_play = QPushButton("▶ Play")
        self._btn_play.setStyleSheet(_BTN_STYLE)
        self._btn_play.setFixedWidth(80)
        self._btn_play.clicked.connect(self.toggle)

        self._btn_stop = QPushButton("⏹ Stop")
        self._btn_stop.setStyleSheet(_BTN_STYLE)
        self._btn_stop.clicked.connect(self.stop)

        self._btn_forward = QPushButton("10s ⏭")
        self._btn_forward.setStyleSheet(_BTN_STYLE)
        self._btn_forward.clicked.connect(lambda: self.forward(10))

        row.addWidget(self._btn_backward)
        row.addWidget(self._btn_play)
        row.addWidget(self._btn_stop)
        row.addWidget(self._btn_forward)
        return group

    def _build_volume_control(self):
        """🔊 icon + slider (0–100) + percentage label."""
        row = QHBoxLayout()
        row.setSpacing(4)

        icon = QLabel("🔊")
        icon.setStyleSheet("font-size:16px;")

        self._vol_slider = _ClickSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(100)
        self._vol_slider.setStyleSheet(_SLIDER_STYLE)

        self._vol_pct = QLabel("100%")
        self._vol_pct.setFixedWidth(36)
        self._vol_pct.setStyleSheet("color:#aaa;font-size:12px;")

        self._vol_slider.valueChanged.connect(lambda v: self.set_volume(v / 100))
        self._vol_slider.valueChanged.connect(lambda v: self._vol_pct.setText(f"{v}%"))

        row.addWidget(icon)
        row.addWidget(self._vol_slider)
        row.addWidget(self._vol_pct)
        return row

    def _build_speed_control(self):
        """'Speed:' label + dropdown (0.25× … 2.0×)."""
        row = QHBoxLayout()
        row.setSpacing(4)

        label = QLabel("Speed:")
        label.setStyleSheet("color:#aaa;font-size:12px;")

        self._speed_box = QComboBox()
        self._speed_box.addItems(["0.25x", "0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"])
        self._speed_box.setCurrentText("1.0x")
        self._speed_box.setFixedWidth(72)
        self._speed_box.setStyleSheet(
            "QComboBox{background:#333;color:#fff;border:none;border-radius:4px;"
            "padding:3px 6px;font-size:12px;}"
            "QComboBox QAbstractItemView{background:#333;color:#fff;}"
        )
        self._speed_box.currentTextChanged.connect(
            lambda t: self.set_playback_speed(float(t.rstrip("x")))
        )

        row.addWidget(label)
        row.addWidget(self._speed_box)
        return row

    def _build_notes(self):
        """Search box + Go button — emits search_requested(text) on click."""
        label = QLabel("Search scene")
        label.setStyleSheet("color:#888;font-size:11px;margin-top:4px;")
        self._root.addWidget(label)

        row = QHBoxLayout()

        self._notes = QTextEdit()
        self._notes.setPlaceholderText("Describe a scene and press Go…")
        self._notes.setFixedHeight(60)
        self._notes.setStyleSheet(
            "QTextEdit{background:#2a2a2a;color:#fff;border:1px solid #444;"
            "border-radius:4px;padding:4px;font-size:13px;}"
        )

        self._btn_go = QPushButton("Go")
        self._btn_go.setFixedSize(52, 60)
        self._btn_go.setStyleSheet(
            "QPushButton{background:#1db954;color:#fff;border:none;"
            "border-radius:4px;font-size:14px;font-weight:bold;}"
            "QPushButton:hover{background:#17a045;}"
            "QPushButton:pressed{background:#128a38;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )
        self._btn_go.clicked.connect(self._on_go)

        row.addWidget(self._notes)
        row.addWidget(self._btn_go)
        self._root.addLayout(row)

    def _on_go(self):
        query = self._notes.toPlainText().strip()
        if not query:
            return
        self._btn_go.setEnabled(False)
        self._btn_go.setText("…")
        self.search_requested.emit(query)

    def _build_player(self):
        """Qt multimedia backend + signal wiring."""
        self.audio = QAudioOutput()
        self.audio.setVolume(1.0)

        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.seek_to.connect(self.seek_seconds)       # thread-safe seek from background threads
        self.seek_to.connect(self._on_seek_done)      # re-enable Go button after seek
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.chunk_ready.connect(self._on_chunk_ready)

        self._seeking = False
        self._timer = QTimer()
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._sync_position)
        self._timer.start()

    # ── internal slots ────────────────────────────────────────────────────────

    def _on_duration_changed(self, ms: int):
        self._seek.setRange(0, ms)
        self._dur_label.setText(_fmt(ms))

    def _on_chunk_ready(self, start_sec: float, end_sec: float):
        self._seek.add_marker(int(start_sec * 1000), int(end_sec * 1000))

    def _on_position_changed(self, ms: int):
        if not self._seeking:
            self._seek.setValue(ms)
            self._time_label.setText(_fmt(ms))

    def _sync_position(self):
        self._on_position_changed(self.player.position())

    def _on_seek(self, ms: int):
        self._seeking = True
        self.player.setPosition(ms)
        self._time_label.setText(_fmt(ms))
        self._seeking = False

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self._btn_play.setText("⏸ Pause")
        else:
            self._btn_play.setText("▶ Play")

    def _on_seek_done(self):
        self._btn_go.setEnabled(True)
        self._btn_go.setText("Go")

    # ── public API ────────────────────────────────────────────────────────────

    def open(self, filename: str):
        self.player.setSource(QUrl.fromLocalFile(filename))

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()

    def restart(self):
        self.seek(0)
        self.play()

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.pause()
        else:
            self.play()

    def seek(self, milliseconds: int):
        self.player.setPosition(milliseconds)

    def seek_seconds(self, seconds: float):
        if seconds < 0:
            return
        self.seek(int(seconds * 1000))

    def forward(self, seconds=10):
        self.player.setPosition(self.player.position() + int(seconds * 1000))

    def backward(self, seconds=10):
        self.player.setPosition(max(0, self.player.position() - int(seconds * 1000)))

    def set_playback_speed(self, speed: float):
        self.player.setPlaybackRate(speed)

    def playback_speed(self):
        return self.player.playbackRate()

    def set_volume(self, volume: float):
        self.audio.setVolume(volume)

    def volume(self):
        return self.audio.volume()

    def current_time(self):
        return self.player.position()

    def current_seconds(self):
        return self.player.position() / 1000

    def duration(self):
        return self.player.duration()

    def duration_seconds(self):
        return self.player.duration() / 1000

    def progress(self):
        d = self.player.duration()
        return 0 if d == 0 else self.player.position() / d * 100

    def notes(self) -> str:
        return self._notes.toPlainText()

    def show(self):
        self.window.show()

    def fullscreen(self):
        self.window.showFullScreen()

    def normal_screen(self):
        self.window.showNormal()

    def close(self):
        self.stop()
        self.window.close()

    def exec(self):
        self.show()
        return self.app.exec()
