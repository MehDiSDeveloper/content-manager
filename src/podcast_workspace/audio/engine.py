"""Playback engine: ffmpeg decodes to raw float PCM, QAudioSink plays it.

Threads:
- UI thread: `Player` facade. Sends commands as queued signals, receives position/state.
- Engine thread (QThread): `_Engine` owns the QAudioSink and a 10 ms pump timer.
- Reader thread (per decoder): blocking reads from ffmpeg's stdout into a bounded buffer.

Timing: position = segment start + processedUSecs * speed. Every seek or speed change
starts a new ffmpeg segment with input seeking (-ss before -i, frame-accurate for audio).
Sample rate: output runs at the device mix rate. If the file differs, ffmpeg resamples once
with soxr (or high-quality swr); Windows' shared-mode mixer then gets a native-rate stream.
"""

import subprocess
import threading
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from podcast_workspace.audio.ffmpeg import (
    NO_WINDOW,
    FfmpegMissingError,
    has_filter,
    probe_stream,
    require_ffmpeg,
)
from podcast_workspace.audio.waveform import seek_cache

SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
MIN_SPEED, MAX_SPEED = SPEEDS[0], SPEEDS[-1]
PUMP_INTERVAL_MS = 10
SINK_BUFFER_MS = 300
DECODE_AHEAD_MS = 2000
POSITION_INTERVAL_MS = 30


class PlayerState(StrEnum):
    EMPTY = "empty"
    LOADING = "loading"
    PAUSED = "paused"
    PLAYING = "playing"
    ERROR = "error"


class _Decoder:
    """One ffmpeg process decoding from a start position into a bounded byte buffer."""

    def __init__(self, args: list[str], max_bytes: int) -> None:
        self._max = max_bytes
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._closed = False
        self.eof = False
        self.produced = 0
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
        self._thread = threading.Thread(target=self._run, name="ffmpeg-reader", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        stdout = self._proc.stdout
        assert stdout is not None
        while True:
            with self._cond:
                while len(self._buf) >= self._max and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
            try:
                chunk = stdout.read1(65536)
            except (OSError, ValueError):
                chunk = b""
            with self._cond:
                if not chunk:
                    self.eof = True
                    return
                self._buf += chunk
                self.produced += len(chunk)

    def available(self) -> int:
        with self._cond:
            return len(self._buf)

    def take(self, n: int) -> bytes:
        with self._cond:
            data = bytes(self._buf[:n])
            del self._buf[:n]
            self._cond.notify()
            return data

    @property
    def drained(self) -> bool:
        with self._cond:
            return self.eof and not self._buf

    def error_text(self) -> str:
        if self._proc.poll() is None or self._proc.returncode == 0 or self._proc.stderr is None:
            return ""
        return self._proc.stderr.read().decode("utf-8", "replace").strip()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()
        for pipe in (self._proc.stdout, self._proc.stderr):
            if pipe is not None:
                pipe.close()


class _Engine(QObject):
    position = Signal(int, int)  # position_ms, seek generation
    state = Signal(str)
    loaded = Signal(int)  # duration_ms (0 if unknown)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(PUMP_INTERVAL_MS)
        self._timer.timeout.connect(self._pump)
        self._devices: QMediaDevices | None = None
        self._device: QAudioDevice | None = None
        self._sink: QAudioSink | None = None
        self._io = None
        self._decoder: _Decoder | None = None
        self._path: Path | None = None
        self._decode_path: Path | None = None  # the file itself, or its exact-seek FLAC cache
        self._rate = 0
        self._channels = 0
        self._out_rate = 0
        self._out_channels = 0
        self._float = True
        self._frame_bytes = 0
        self._duration = 0
        self._speed = 1.0
        self._seg_start = 0
        self._playing = False
        self._generation = 0
        self._last_emitted = -1

    # commands -------------------------------------------------------------------------
    @Slot(str, int, int)
    def load(self, path: str, duration_hint: int, generation: int) -> None:
        self._teardown()
        self._generation = generation
        self._path = Path(path)
        self.state.emit(PlayerState.LOADING)
        try:
            if not self._path.is_file():
                raise FileNotFoundError(path)
            info = probe_stream(self._path)
            require_ffmpeg()
        except (OSError, ValueError, FfmpegMissingError, subprocess.SubprocessError) as exc:
            self._path = None
            self.failed.emit(str(exc) or type(exc).__name__)
            self.state.emit(PlayerState.ERROR)
            return
        if self._devices is None:
            self._devices = QMediaDevices(self)
            self._devices.audioOutputsChanged.connect(self._on_outputs_changed)
        self._decode_path = seek_cache(self._path) or self._path
        self._rate, self._channels = info.sample_rate, info.channels
        self._duration = info.duration_ms or duration_hint
        self._seg_start = 0
        self._build_sink()
        self._start_segment(0)
        self.loaded.emit(self._duration)
        self.state.emit(PlayerState.PAUSED)
        self._emit_position(force=True)

    @Slot(int)
    def set_duration(self, duration_ms: int) -> None:
        """Exact duration from the waveform pass (containers can misreport it)."""
        if duration_ms > 0:
            self._duration = duration_ms

    @Slot()
    def seek_cache_ready(self) -> None:
        """The waveform pass wrote an exact-seek cache: use it from the next segment on."""
        if self._path is None:
            return
        cache = seek_cache(self._path)
        if cache is None or cache == self._decode_path:
            return
        self._decode_path = cache
        if not self._playing:  # invisible while paused; while playing wait for the next seek
            self._start_segment(self._position_now())

    @Slot()
    def warm_up(self) -> None:
        """First-use costs (audio subsystem, ffmpeg feature probe) paid before the user waits."""
        QMediaDevices.defaultAudioOutput()
        has_filter("soxr")

    @Slot()
    def play(self) -> None:
        if self._path is None or self._sink is None or self._playing:
            return
        if self._decoder is not None and self._decoder.drained and self._at_end():
            self._start_segment(0)  # finished: play again from the top
        self._playing = True
        if self._sink.state() == QtAudio.State.SuspendedState:
            self._sink.resume()
        elif self._io is None:
            self._io = self._sink.start()
        self._timer.start()
        self.state.emit(PlayerState.PLAYING)

    @Slot()
    def pause(self) -> None:
        if not self._playing or self._sink is None:
            return
        self._playing = False
        if self._io is not None:
            self._sink.suspend()
        self._timer.stop()
        self.state.emit(PlayerState.PAUSED)
        self._emit_position(force=True)

    @Slot(int, int)
    def seek(self, position_ms: int, generation: int) -> None:
        self._generation = generation
        if self._path is None:
            return
        self._start_segment(self._clamp(position_ms))
        self._emit_position(force=True)

    @Slot(float, int)
    def set_speed(self, speed: float, generation: int) -> None:
        speed = min(MAX_SPEED, max(MIN_SPEED, speed))
        if abs(speed - self._speed) < 1e-6:
            return
        current = self._position_now()
        self._speed = speed
        self._generation = generation
        if self._path is not None:
            self._start_segment(current)

    @Slot()
    def unload(self) -> None:
        self._teardown()
        self.state.emit(PlayerState.EMPTY)

    @Slot()
    def shutdown(self) -> None:
        self._teardown()
        self._timer.stop()

    # internals ------------------------------------------------------------------------
    def _build_sink(self) -> None:
        device = QMediaDevices.defaultAudioOutput()
        self._device = device
        preferred = device.preferredFormat()
        out_rate = preferred.sampleRate() if preferred.sampleRate() > 0 else self._rate
        candidates = [
            (1 if self._channels == 1 else 2, QAudioFormat.SampleFormat.Float),
            (2, QAudioFormat.SampleFormat.Float),
            (2, QAudioFormat.SampleFormat.Int16),
        ]
        chosen = QAudioFormat()
        for channels, sample_format in candidates:
            fmt = QAudioFormat()
            fmt.setSampleRate(out_rate)
            fmt.setChannelCount(channels)
            fmt.setSampleFormat(sample_format)
            chosen = fmt
            if device.isFormatSupported(fmt):
                break
        self._out_rate = chosen.sampleRate()
        self._out_channels = chosen.channelCount()
        self._float = chosen.sampleFormat() == QAudioFormat.SampleFormat.Float
        self._frame_bytes = chosen.bytesPerFrame()
        self._sink = QAudioSink(device, chosen, self)
        self._sink.setBufferSize(self._bytes_for_ms(SINK_BUFFER_MS))
        self._io = None

    def _bytes_for_ms(self, ms: int) -> int:
        frames = self._out_rate * ms // 1000
        return frames * self._frame_bytes

    def _decode_args(self, start_ms: int) -> list[str]:
        assert self._decode_path is not None
        filters: list[str] = []
        if abs(self._speed - 1.0) > 1e-6:
            filters.append(f"atempo={self._speed:g}")
        if self._out_rate != self._rate:
            if has_filter("soxr"):
                filters.append(f"aresample={self._out_rate}:resampler=soxr:precision=28")
            else:
                filters.append(f"aresample={self._out_rate}:filter_size=64:cutoff=0.97")
        codec = ("f32le", "pcm_f32le") if self._float else ("s16le", "pcm_s16le")
        args = [str(require_ffmpeg()), "-hide_banner", "-nostdin", "-loglevel", "error"]
        if start_ms > 0:
            args += ["-ss", f"{start_ms / 1000:.3f}"]
        args += ["-i", str(self._decode_path), "-map", "0:a:0", "-vn", "-sn", "-dn"]
        if filters:
            args += ["-af", ",".join(filters)]
        if self._out_channels != self._channels:
            args += ["-ac", str(self._out_channels)]
        args += ["-f", codec[0], "-acodec", codec[1], "pipe:1"]
        return args

    def _start_segment(self, start_ms: int) -> None:
        if self._decoder is not None:
            self._decoder.close()
            self._decoder = None
        if self._sink is not None:
            self._sink.reset()  # drop queued audio; processedUSecs restarts at 0
            self._sink.stop()
            self._io = None
        self._seg_start = start_ms
        try:
            self._decoder = _Decoder(
                self._decode_args(start_ms), self._bytes_for_ms(DECODE_AHEAD_MS)
            )
        except OSError as exc:
            self.failed.emit(str(exc))
            self._playing = False
            self.state.emit(PlayerState.ERROR)
            return
        if self._playing and self._sink is not None:
            self._io = self._sink.start()
            self._timer.start()

    def _pump(self) -> None:
        sink, decoder = self._sink, self._decoder
        if sink is None or decoder is None or self._io is None:
            return
        free = sink.bytesFree()
        available = decoder.available()
        n = min(free, available)
        n -= n % self._frame_bytes
        if n > 0:
            self._io.write(decoder.take(n))
        if decoder.drained and sink.state() == QtAudio.State.IdleState:
            self._finish(decoder)
            return
        self._emit_position()

    def _finish(self, decoder: _Decoder) -> None:
        error = decoder.error_text() if decoder.produced == 0 else ""
        self._playing = False
        self._timer.stop()
        if error:
            self.failed.emit(error)
            self.state.emit(PlayerState.ERROR)
            return
        if self._duration <= 0 or decoder.produced:
            played_ms = self._seg_start + self._segment_ms(decoder.produced)
            self._duration = max(self._duration, played_ms)
        self._seg_start = self._duration
        if self._sink is not None:
            self._sink.stop()
            self._io = None
        self._emit_position(force=True)
        self.state.emit(PlayerState.PAUSED)

    def _segment_ms(self, output_bytes: int) -> int:
        frames = output_bytes // max(1, self._frame_bytes)
        return int(frames * 1000 / max(1, self._out_rate) * self._speed)

    def _at_end(self) -> bool:
        return self._duration > 0 and self._position_now() >= self._duration - 50

    def _position_now(self) -> int:
        if self._sink is None or self._io is None:
            return self._seg_start
        played = self._sink.processedUSecs() / 1000 * self._speed
        return self._clamp(self._seg_start + int(played))

    def _clamp(self, ms: int) -> int:
        upper = self._duration if self._duration > 0 else ms
        return max(0, min(ms, upper))

    def _emit_position(self, force: bool = False) -> None:
        now = self._position_now()
        if force or abs(now - self._last_emitted) >= POSITION_INTERVAL_MS:
            self._last_emitted = now
            self.position.emit(now, self._generation)

    def _on_outputs_changed(self) -> None:
        """Default output changed (headphones plugged in...): move playback to it."""
        if self._path is None or self._sink is None:
            return
        device = QMediaDevices.defaultAudioOutput()
        if self._device is not None and device.id() == self._device.id():
            return
        position = self._position_now()
        self._sink.stop()
        self._sink.deleteLater()
        self._build_sink()
        self._start_segment(position)

    def _teardown(self) -> None:
        self._timer.stop()
        self._playing = False
        if self._decoder is not None:
            self._decoder.close()
            self._decoder = None
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
            self._sink = None
        self._io = None
        self._path = None
        self._decode_path = None
        self._duration = 0
        self._seg_start = 0
        self._last_emitted = -1


class Player(QObject):
    """UI-thread facade. All calls return immediately; the engine thread does the work."""

    position_changed = Signal(int)
    state_changed = Signal(object)  # PlayerState
    duration_changed = Signal(int)
    speed_changed = Signal(float)
    error = Signal(str)

    _cmd_load = Signal(str, int, int)
    _cmd_play = Signal()
    _cmd_pause = Signal()
    _cmd_seek = Signal(int, int)
    _cmd_speed = Signal(float, int)
    _cmd_duration = Signal(int)
    _cmd_seek_cache = Signal()
    _cmd_warm_up = Signal()
    _cmd_unload = Signal()
    _cmd_shutdown = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("audio-engine")
        self._engine = _Engine()
        self._engine.moveToThread(self._thread)
        queued = Qt.ConnectionType.QueuedConnection
        self._cmd_load.connect(self._engine.load, queued)
        self._cmd_play.connect(self._engine.play, queued)
        self._cmd_pause.connect(self._engine.pause, queued)
        self._cmd_seek.connect(self._engine.seek, queued)
        self._cmd_speed.connect(self._engine.set_speed, queued)
        self._cmd_duration.connect(self._engine.set_duration, queued)
        self._cmd_unload.connect(self._engine.unload, queued)
        self._cmd_seek_cache.connect(self._engine.seek_cache_ready, queued)
        self._cmd_warm_up.connect(self._engine.warm_up, queued)
        self._cmd_shutdown.connect(
            self._engine.shutdown, Qt.ConnectionType.BlockingQueuedConnection
        )
        self._engine.position.connect(self._on_position, queued)
        self._engine.state.connect(self._on_state, queued)
        self._engine.loaded.connect(self._on_loaded, queued)
        self._engine.failed.connect(self.error, queued)
        self._thread.start(QThread.Priority.TimeCriticalPriority)
        self._cmd_warm_up.emit()

        self._state = PlayerState.EMPTY
        self._position = 0
        self._duration = 0
        self._speed = 1.0
        self._generation = 0
        self._source = ""
        self._exact_duration = False

    # state ------------------------------------------------------------------------------
    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def position(self) -> int:
        return self._position

    @property
    def duration(self) -> int:
        return self._duration

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def source(self) -> str:
        return self._source

    @property
    def is_playing(self) -> bool:
        return self._state is PlayerState.PLAYING

    # commands ---------------------------------------------------------------------------
    def load(self, path: str, duration_hint_ms: int = 0) -> None:
        self._source = path
        self._exact_duration = False
        self._generation += 1
        self._position = 0
        self._duration = duration_hint_ms
        self.position_changed.emit(0)
        self.duration_changed.emit(duration_hint_ms)
        self._cmd_load.emit(path, duration_hint_ms, self._generation)

    def unload(self) -> None:
        self._source = ""
        self._generation += 1
        self._position = 0
        self._duration = 0
        self._cmd_unload.emit()

    def play(self) -> None:
        if self._source:  # queued behind a pending load, so it is safe while LOADING
            self._cmd_play.emit()

    def pause(self) -> None:
        self._cmd_pause.emit()

    def toggle(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def seek(self, position_ms: int) -> None:
        if not self._source:
            return
        upper = self._duration if self._duration > 0 else max(position_ms, 0)
        target = max(0, min(position_ms, upper))
        self._generation += 1
        self._position = target  # the UI moves at once; the engine catches up
        self.position_changed.emit(target)
        self._cmd_seek.emit(target, self._generation)

    def skip(self, delta_ms: int) -> None:
        self.seek(self._position + delta_ms)

    def set_speed(self, speed: float) -> None:
        speed = min(MAX_SPEED, max(MIN_SPEED, round(speed, 2)))
        if speed == self._speed:
            return
        self._speed = speed
        self._generation += 1
        self.speed_changed.emit(speed)
        self._cmd_speed.emit(speed, self._generation)

    def step_speed(self, direction: int) -> None:
        index = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - self._speed))
        index = max(0, min(len(SPEEDS) - 1, index + direction))
        self.set_speed(SPEEDS[index])

    def set_exact_duration(self, duration_ms: int) -> None:
        if duration_ms > 0 and duration_ms != self._duration:
            self._exact_duration = True
            self._duration = duration_ms
            self.duration_changed.emit(duration_ms)
            self._cmd_duration.emit(duration_ms)

    def seek_cache_ready(self) -> None:
        self._cmd_seek_cache.emit()

    def shutdown(self) -> None:
        if self._thread.isRunning():
            self._cmd_shutdown.emit()
            self._thread.quit()
            self._thread.wait(3000)

    # engine events ------------------------------------------------------------------------
    def _on_position(self, position_ms: int, generation: int) -> None:
        if generation != self._generation:
            return  # stale report from before the latest seek
        self._position = position_ms
        self.position_changed.emit(position_ms)

    def _on_state(self, value: str) -> None:
        self._state = PlayerState(value)
        self.state_changed.emit(self._state)

    def _on_loaded(self, duration_ms: int) -> None:
        if duration_ms > 0 and not self._exact_duration and duration_ms != self._duration:
            self._duration = duration_ms
            self.duration_changed.emit(duration_ms)
