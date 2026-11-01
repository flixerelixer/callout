"""Audio capture: the game's own audio (WASAPI process loopback) or everything
you hear (WASAPI output loopback). Everything is delivered as 16 kHz mono
float32, which is what the VAD and Whisper expect.

Windows-only modules are imported lazily so the rest of the app (and the
tests) can be imported anywhere.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

TARGET_RATE = 16000


class Downmixer:
    """Turns interleaved PCM bytes into 16 kHz mono float32, keeping resampler
    state between chunks so there are no clicks at chunk borders."""

    def __init__(self, rate: int, channels: int, bits: int):
        if bits not in (16, 32):
            raise ValueError(f"Unsupported sample size: {bits} bits")
        self.rate = rate
        self.channels = max(1, channels)
        self.bits = bits
        self._leftover = b""
        self._resampler = None
        if rate != TARGET_RATE:
            import soxr

            self._resampler = soxr.ResampleStream(rate, TARGET_RATE, 1, dtype="float32", quality="HQ")

    def __call__(self, data: bytes) -> np.ndarray:
        data = self._leftover + data
        frame_bytes = self.channels * self.bits // 8
        usable = len(data) - (len(data) % frame_bytes)
        self._leftover = data[usable:]
        if usable == 0:
            return np.zeros(0, dtype=np.float32)
        if self.bits == 32:
            pcm = np.frombuffer(data[:usable], dtype=np.float32)
        else:
            pcm = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768.0
        mono = pcm.reshape(-1, self.channels).mean(axis=1).astype(np.float32)
        if self._resampler is not None:
            mono = self._resampler.resample_chunk(mono)
        return np.ascontiguousarray(mono, dtype=np.float32)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class AudioSource:
    description = "audio"

    def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def read(self) -> np.ndarray | None:  # pragma: no cover - interface
        """Return any new 16 kHz mono samples, or None when nothing arrived."""
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ProcessLoopbackSource(AudioSource):
    """Captures only the audio of one process (and its children).

    Needs Windows 10 build 20348+ or Windows 11. Must be created and read on
    the same thread.
    """

    def __init__(self, pid: int, process_name: str):
        from proctap._native import ProcessLoopback  # Windows-only extension

        self.pid = pid
        self._cap = ProcessLoopback(pid)
        fmt = self._cap.get_format() or {}
        self.process_specific = bool(self._cap.is_process_specific())
        rate = int(fmt.get("sample_rate", 48000))
        channels = int(fmt.get("channels", 2))
        bits = int(fmt.get("bits_per_sample", 32))
        self._mix = Downmixer(rate, channels, bits)
        if self.process_specific:
            self.description = f"{process_name} only"
        else:
            # proctap silently falls back to the whole output mix if the
            # per-process API is unavailable.
            self.description = "All system audio (game-only capture unavailable)"
            err = self._cap.get_last_error()
            if err:
                log.warning("Process loopback unavailable: %s", err)
        log.info("Process capture pid=%s format=%s process_specific=%s", pid, fmt, self.process_specific)

    def start(self) -> None:
        self._cap.start()

    def read(self) -> np.ndarray | None:
        chunks = []
        # read() returns at most one WASAPI packet (~10 ms) per call.
        for _ in range(200):
            data = self._cap.read()
            if not data:
                break
            chunks.append(data)
        if not chunks:
            return None
        return self._mix(b"".join(chunks))

    def stop(self) -> None:
        try:
            self._cap.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("stop failed: %s", exc)


def list_output_devices() -> list[str]:
    """Names of output devices that can be captured (Windows only)."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []
    names: list[str] = []
    p = pyaudio.PyAudio()
    try:
        for dev in p.get_loopback_device_info_generator():
            name = str(dev.get("name", "")).replace(" [Loopback]", "")
            if name and name not in names:
                names.append(name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not list output devices: %s", exc)
    finally:
        p.terminate()
    return names


class SystemLoopbackSource(AudioSource):
    """Captures everything playing on an output device (default: the Windows
    default speakers/headset)."""

    def __init__(self, device_name: str = ""):
        import pyaudiowpatch as pyaudio

        self._pyaudio = pyaudio
        self._p = pyaudio.PyAudio()
        try:
            dev = self._find_device(device_name)
        except Exception:
            self._p.terminate()
            raise
        self._dev = dev
        self._rate = int(dev["defaultSampleRate"])
        self._channels = max(1, int(dev["maxInputChannels"]))
        self._mix = Downmixer(self._rate, self._channels, 32)
        self._buf: collections.deque[bytes] = collections.deque()
        self._lock = threading.Lock()
        self._stream = None
        name = str(dev.get("name", "output")).replace(" [Loopback]", "")
        self.description = f"All audio on {name}"

    def _find_device(self, device_name: str) -> dict:
        p = self._p
        if device_name:
            for dev in p.get_loopback_device_info_generator():
                if device_name.lower() in str(dev.get("name", "")).lower():
                    return dev
            log.warning("Output device %r not found; using the default one", device_name)
        return p.get_default_wasapi_loopback()

    def _callback(self, in_data, frame_count, time_info, status):  # noqa: ARG002
        with self._lock:
            self._buf.append(in_data)
            # Never let the buffer grow without bound (about 5 s).
            while len(self._buf) > 500:
                self._buf.popleft()
        return (None, self._pyaudio.paContinue)

    def start(self) -> None:
        self._stream = self._p.open(
            format=self._pyaudio.paFloat32,
            channels=self._channels,
            rate=self._rate,
            input=True,
            input_device_index=self._dev["index"],
            frames_per_buffer=max(256, self._rate // 50),
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def read(self) -> np.ndarray | None:
        with self._lock:
            if not self._buf:
                return None
            data = b"".join(self._buf)
            self._buf.clear()
        return self._mix(data)

    def stop(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        except Exception as exc:  # noqa: BLE001
            log.debug("stop failed: %s", exc)
        finally:
            self._p.terminate()


# ---------------------------------------------------------------------------
# Picking and switching sources
# ---------------------------------------------------------------------------


def find_process(name: str) -> int | None:
    """PID of the first running process with this executable name."""
    import psutil

    target = name.lower().strip()
    if not target:
        return None
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info.get("name") or "").lower() == target:
                return proc.pid
        except Exception:  # noqa: BLE001
            continue
    return None


def pid_alive(pid: int) -> bool:
    import psutil

    return psutil.pid_exists(pid)


class CaptureManager:
    """Opens the right source for the chosen mode and switches when the game
    starts or quits. Create and use it on a single thread."""

    RECHECK_S = 3.0

    def __init__(self, mode: str, process_name: str, device_name: str,
                 on_status: Callable[[str], None] | None = None):
        self.mode = mode if mode in ("auto", "process", "system") else "auto"
        self.process_name = process_name or "cs2.exe"
        self.device_name = device_name
        self._on_status = on_status or (lambda _msg: None)
        self.source: AudioSource | None = None
        self._pid: int | None = None
        self._last_check = -1e9
        self._process_failed_for: int | None = None

    @property
    def description(self) -> str:
        if self.source is None:
            return f"Waiting for {self.process_name}…"
        return self.source.description

    def _open(self, source: AudioSource) -> None:
        self.close()
        source.start()
        self.source = source
        self._on_status(source.description)

    def _try_process(self, pid: int) -> bool:
        try:
            self._open(ProcessLoopbackSource(pid, self.process_name))
            self._pid = pid
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Game-only capture failed for pid %s: %s", pid, exc)
            self._process_failed_for = pid
            return False

    def _try_system(self) -> bool:
        try:
            self._open(SystemLoopbackSource(self.device_name))
            self._pid = None
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("System audio capture failed: %s", exc)
            self._on_status(f"Audio capture failed: {exc}")
            return False

    def poll(self) -> None:
        """Re-evaluate which source to use. Cheap; call it often."""
        now = time.monotonic()
        if now - self._last_check < self.RECHECK_S:
            return
        self._last_check = now

        if self.mode == "system":
            if self.source is None:
                self._try_system()
            return

        # Game currently captured: keep it while the process lives.
        if self._pid is not None:
            if pid_alive(self._pid):
                return
            log.info("%s exited", self.process_name)
            self.close()

        pid = find_process(self.process_name)
        if pid is not None and pid != self._process_failed_for:
            if self._try_process(pid):
                return

        if self.mode == "auto":
            if self.source is None:
                self._try_system()
        elif self.source is None:
            self._on_status(f"Waiting for {self.process_name}…")

    def read(self) -> np.ndarray | None:
        self.poll()
        if self.source is None:
            return None
        try:
            return self.source.read()
        except Exception as exc:  # noqa: BLE001
            log.warning("Audio read failed (%s); reopening", exc)
            self.close()
            self._last_check = -1e9
            return None

    def close(self) -> None:
        if self.source is not None:
            self.source.stop()
        self.source = None
        self._pid = None
