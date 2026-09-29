"""Playback engine: ffmpeg decodes to raw float PCM, QAudioSink plays it.

Threads:
- UI thread: `Player` facade. Sends commands as queued signals, receives position/state.
- Engine thread (QThread): `_Engine` owns the QAudioSink and a 10 ms pump timer.
- Reader thread (per decoder): blocking reads from ffmpeg's stdout into a bounded buffer.

Timing: position = segment start + processedUSecs * speed. Every seek or speed change
starts a new ffmpeg segment with input seeking (-ss before -i, frame-accurate for audio).
Pause trimming: the reader passes each chunk through a `Splicer`, which leaves the cut
stretches out and maps a played frame back to the file's timeline, so positions never leave
it. The decode-ahead bound counts kept audio, so a long pause is read past at decode speed.
Sample rate: output runs at the device mix rate. If the file differs, ffmpeg resamples once
with soxr (or high-quality swr); Windows' shared-mode mixer then gets a native-rate stream.
"""

import subprocess
import threading
from enum import StrEnum
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from podcast_workspace.audio.ffmpeg import (
    NO_WINDOW,
    FfmpegMissingError,
    has_filter,
    probe_stream,
    require_ffmpeg,
)
from podcast_workspace.audio.silence import DEFAULT_KEEP_MS, Span, Splicer, clamp_keep, cuts_for
from podcast_workspace.audio.waveform import seek_cache

SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)  # the presets, and what - and = step through
MIN_SPEED, MAX_SPEED = SPEEDS[0], SPEEDS[-1]
SPEED_STEP = 0.05  # the speed slider's resolution
SPEED_SETTLE_MS = 200  # a slider speed reaches the engine once the slider rests
PUMP_INTERVAL_MS = 10
SINK_BUFFER_MS = 300
DECODE_AHEAD_MS = 2000
POSITION_INTERVAL_MS = 30
CUTS_SETTLE_MS = 300  # a keep-pause change reaches the engine once the slider rests
MAX_VOLUME = 100
VOLUME_SETTLE_MS = 500  # the level is written to settings once the slider rests


class PlayerState(StrEnum):
    EMPTY = "empty"
    LOADING = "loading"
    PAUSED = "paused"
    PLAYING = "playing"
    ERROR = "error"


class _Decoder:
    """One ffmpeg process decoding from a start position into a bounded byte buffer."""

    def __init__(self, args: list[str], max_bytes: int, splicer: Splicer) -> None:
        self._max = max_bytes
        self._splicer = splicer
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
                    self._buf += self._splicer.flush()
                    self.eof = True
                    return
                self._buf += self._splicer.feed(chunk)
                self.produced += len(chunk)  # source bytes, cut ones included

    def available(self) -> int:
        with self._cond:
            return len(self._buf)

    def take(self, n: int) -> bytes:
        with self._cond:
            data = bytes(self._buf[:n])
            del self._buf[:n]
            self._cond.notify()
            return data

    def source_ms(self, out_frame: int) -> float:
        with self._cond:
            return self._splicer.source_ms(out_frame)

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
        self._gain = 1.0  # linear sink volume
        self._cuts: tuple[Span, ...] = ()
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

    @Slot(object, int)
    def set_cuts(self, cuts: tuple[Span, ...], generation: int) -> None:
        """Stretches to leave out while playing (file timeline), from the current position on."""
        if cuts == self._cuts:
            return
        current = self._position_now()
        self._cuts = cuts
        self._generation = generation
        if self._path is not None:
            self._start_segment(current)

    @Slot(float)
    def set_gain(self, gain: float) -> None:
        self._gain = max(0.0, min(1.0, gain))
        if self._sink is not None:
            self._sink.setVolume(self._gain)

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
        self._sink.setVolume(self._gain)
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
        splicer = Splicer(
            self._cuts,
            start_ms,
            1000 * self._speed / self._out_rate,
            self._out_channels,
            np.float32 if self._float else np.int16,
        )
        try:
            self._decoder = _Decoder(
                self._decode_args(start_ms), self._bytes_for_ms(DECODE_AHEAD_MS), splicer
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
        if self._sink is None or self._io is None or self._decoder is None:
            return self._seg_start
        played_frames = self._sink.processedUSecs() * self._out_rate // 1_000_000
        return self._clamp(int(self._decoder.source_ms(played_frames)))

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
        self._cuts = ()
        self._seg_start = 0
        self._last_emitted = -1


class Player(QObject):
    """UI-thread facade. All calls return immediately; the engine thread does the work."""

    position_changed = Signal(int)
    state_changed = Signal(object)  # PlayerState
    duration_changed = Signal(int)
    speed_changed = Signal(float)
    error = Signal(str)
    silence_changed = Signal()  # the setting, or the pauses found in the file
    keep_pause_settled = Signal(int)  # keep_ms once the slider rests, to remember
    volume_changed = Signal()  # level or mute
    volume_settled = Signal(int)  # an audible level once the slider rests, to remember

    _cmd_load = Signal(str, int, int)
    _cmd_play = Signal()
    _cmd_pause = Signal()
    _cmd_seek = Signal(int, int)
    _cmd_speed = Signal(float, int)
    _cmd_duration = Signal(int)
    _cmd_cuts = Signal(object, int)
    _cmd_gain = Signal(float)
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
        self._cmd_cuts.connect(self._engine.set_cuts, queued)
        self._cmd_gain.connect(self._engine.set_gain, queued)
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
        self._skip_silence = True  # on by default; turning it off lasts for the session
        self._keep_ms = DEFAULT_KEEP_MS
        self._pauses: tuple[Span, ...] | None = None  # None until the waveform is read
        self._cuts: tuple[Span, ...] = ()
        self._settle = QTimer(self, singleShot=True, interval=CUTS_SETTLE_MS)
        self._settle.timeout.connect(self._settle_keep)
        self._speed_settle = QTimer(self, singleShot=True, interval=SPEED_SETTLE_MS)
        self._speed_settle.timeout.connect(self._send_speed)
        self._volume = MAX_VOLUME
        self._last_audible = MAX_VOLUME  # what unmuting a slider pulled down to 0 goes back to
        self._muted = False  # for the session only
        self._volume_settle = QTimer(self, singleShot=True, interval=VOLUME_SETTLE_MS)
        self._volume_settle.timeout.connect(lambda: self.volume_settled.emit(self._last_audible))

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

    @property
    def skip_silence(self) -> bool:
        return self._skip_silence

    @property
    def keep_pause_ms(self) -> int:
        return self._keep_ms

    @property
    def pauses_known(self) -> bool:
        return self._pauses is not None

    @property
    def volume(self) -> int:
        """What is heard, 0–100: 0 while muted."""
        return 0 if self._muted else self._volume

    @property
    def muted(self) -> bool:
        return self._muted or self._volume == 0

    @property
    def level(self) -> int:
        """The set level, 0–100, mute aside: the level saving a voice "as heard" applies."""
        return self._volume or self._last_audible

    @property
    def level_gain(self) -> float:
        """`level` as a linear gain (what the sink gets for it)."""
        return QtAudio.convertVolume(
            self.level / MAX_VOLUME,
            QtAudio.VolumeScale.LogarithmicVolumeScale,
            QtAudio.VolumeScale.LinearVolumeScale,
        )

    def active_cuts(self) -> tuple[Span, ...]:
        """What playback skips right now: nothing while trimming is off."""
        return self.silence_cuts() if self._skip_silence else ()

    def silence_cuts(self) -> tuple[Span, ...]:
        """What the current keep setting skips in this file, whether or not skipping is on."""
        return cuts_for(self._pauses or (), self._keep_ms, self._duration)

    # commands ---------------------------------------------------------------------------
    def load(self, path: str, duration_hint_ms: int = 0) -> None:
        self._source = path
        self._exact_duration = False
        self._generation += 1
        self._position = 0
        self._duration = duration_hint_ms
        self._forget_pauses()  # the engine drops its cuts on load
        self.position_changed.emit(0)
        self.duration_changed.emit(duration_hint_ms)
        self._cmd_load.emit(path, duration_hint_ms, self._generation)

    def unload(self) -> None:
        self._source = ""
        self._generation += 1
        self._position = 0
        self._duration = 0
        self._forget_pauses()
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

    def set_speed(self, speed: float, settle: bool = False) -> None:
        """Snapped to the 5% grid. `settle` (the slider) shows the speed at once and sends it
        to the audio once it stops moving, so dragging does not restart the decoder at every
        step."""
        speed = round(round(speed / SPEED_STEP) * SPEED_STEP, 2)
        speed = min(MAX_SPEED, max(MIN_SPEED, speed))
        if speed == self._speed:
            return
        self._speed = speed
        self.speed_changed.emit(speed)
        if settle:
            self._speed_settle.start()
        else:
            self._send_speed()

    def step_speed(self, direction: int) -> None:
        """To the next preset that way, so an in-between speed goes to its neighbour."""
        if direction > 0:
            self.set_speed(next((s for s in SPEEDS if s > self._speed + 1e-6), MAX_SPEED))
        elif direction < 0:
            self.set_speed(next((s for s in reversed(SPEEDS) if s < self._speed - 1e-6), MIN_SPEED))

    def _send_speed(self) -> None:
        self._speed_settle.stop()
        self._generation += 1
        self._cmd_speed.emit(self._speed, self._generation)

    def set_exact_duration(self, duration_ms: int) -> None:
        if duration_ms > 0 and duration_ms != self._duration:
            self._exact_duration = True
            self._duration = duration_ms
            self.duration_changed.emit(duration_ms)
            self._cmd_duration.emit(duration_ms)

    def seek_cache_ready(self) -> None:
        self._cmd_seek_cache.emit()

    def set_pauses(self, source: str, pauses: tuple[Span, ...]) -> None:
        """The pauses found in `source` (from its waveform); ignored if another file is open."""
        if source != self._source:
            return
        self._pauses = pauses
        self._send_cuts()
        self.silence_changed.emit()

    def restore_keep_pause(self, keep_ms: int | None) -> None:
        """The remembered pause length at startup, applied without being reported back."""
        if keep_ms is not None:
            self._keep_ms = clamp_keep(keep_ms)
        self._send_cuts()
        self.silence_changed.emit()

    def set_skip_silence(self, skip: bool) -> None:
        if skip == self._skip_silence:
            return
        self._skip_silence = skip
        self._send_cuts()
        self.silence_changed.emit()

    def toggle_skip_silence(self) -> None:
        self.set_skip_silence(not self._skip_silence)

    def set_keep_pause(self, keep_ms: int) -> None:
        """Takes effect on screen at once and in the audio once the value stops moving,
        so dragging the slider does not restart the decoder at every step."""
        keep_ms = clamp_keep(keep_ms)
        if keep_ms == self._keep_ms:
            return
        self._keep_ms = keep_ms
        self.silence_changed.emit()
        self._settle.start()

    def restore_volume(self, level: int | None) -> None:
        """The remembered level at startup, applied without being reported back."""
        if level is not None and 0 < level <= MAX_VOLUME:
            self._volume = self._last_audible = level
        self._send_gain()

    def set_volume(self, level: int) -> None:
        """0–100 on a loudness scale. Moving the level unmutes."""
        level = max(0, min(MAX_VOLUME, level))
        if level == self.volume:
            return
        self._volume = level
        self._muted = False
        if level > 0:
            self._last_audible = level
            self._volume_settle.start()
        self._send_gain()

    def step_volume(self, delta: int) -> None:
        """From the set level even while muted, so a step up while muted resumes near it."""
        self.set_volume(self._volume + delta)

    def toggle_mute(self) -> None:
        if self.muted:
            self._muted = False
            if self._volume == 0:
                self._volume = self._last_audible
        else:
            self._muted = True
        self._send_gain()

    def _send_gain(self) -> None:
        # Loudness is logarithmic: a linear gain would crowd everything audible into the
        # slider's top quarter.
        self._cmd_gain.emit(
            QtAudio.convertVolume(
                self.volume / MAX_VOLUME,
                QtAudio.VolumeScale.LogarithmicVolumeScale,
                QtAudio.VolumeScale.LinearVolumeScale,
            )
        )
        self.volume_changed.emit()

    def _settle_keep(self) -> None:
        self._send_cuts()
        self.keep_pause_settled.emit(self._keep_ms)

    def _forget_pauses(self) -> None:
        self._pauses = None
        self._cuts = ()
        self.silence_changed.emit()

    def _send_cuts(self) -> None:
        cuts = self.silence_cuts() if self._skip_silence and self._source else ()
        if cuts == self._cuts:
            return
        self._cuts = cuts
        self._generation += 1
        self._cmd_cuts.emit(cuts, self._generation)

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
