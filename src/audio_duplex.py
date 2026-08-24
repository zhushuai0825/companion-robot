"""单路麦克风常驻 + 播报时可打断（参考小智 Realtime 听模式，不用第二路 arecord）。"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from voice_io import (
    BARGE_IN_ENERGY,
    CHUNK_BYTES,
    RECORD_MAX_SEC,
    SPK,
    VAD_CHUNK_MS,
    VAD_ENERGY,
    VAD_MIN_SPEECH_MS,
    VAD_SILENCE_END_MS,
    _rms,
    _start_arecord_raw,
    _write_pcm_wav,
    start_playback,
)


class DuplexMicrophone:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._alive = False
        self._player: subprocess.Popen | None = None

        self._listening = False
        self._listen_done = False
        self._assume_speaking = False
        self._got_speech = False
        self._frames: list[bytes] = []
        self._speech_run = 0
        self._silence_run = 0

        self._speaking = False
        self._interrupted = False
        self._barge_run = 0

    def start(self) -> None:
        if self._alive:
            return
        self._proc = _start_arecord_raw()
        self._alive = True
        self._thread = threading.Thread(target=self._loop, name="duplex-mic", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._alive = False
        if self._player and self._player.poll() is None:
            self._player.kill()
        if self._proc:
            self._proc.kill()
            self._proc.wait(timeout=1)

    def is_listening(self) -> bool:
        with self._lock:
            return self._listening

    def _finish_listen(self) -> None:
        self._listening = False
        self._listen_done = True
        self._cond.notify_all()

    def _interrupt_playback(self) -> None:
        self._interrupted = True
        if self._player and self._player.poll() is None:
            self._player.kill()
        self._speaking = False
        self._listening = True
        self._assume_speaking = True
        self._got_speech = True
        self._frames = []
        self._silence_run = 0
        self._listen_done = False
        self._cond.notify_all()

    def _loop(self) -> None:
        vad = int(os.getenv("VAD_ENERGY", str(VAD_ENERGY)))
        barge = int(os.getenv("BARGE_IN_ENERGY", str(BARGE_IN_ENERGY)))
        min_speech = max(1, VAD_MIN_SPEECH_MS // VAD_CHUNK_MS)
        silence_end = max(1, VAD_SILENCE_END_MS // VAD_CHUNK_MS)
        barge_trigger = max(3, 200 // VAD_CHUNK_MS)
        max_chunks = max(1, RECORD_MAX_SEC * 1000 // VAD_CHUNK_MS)

        while self._alive and self._proc and self._proc.stdout:
            chunk = self._proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            level = _rms(chunk)
            with self._cond:
                if self._listening:
                    if not self._got_speech:
                        if self._assume_speaking:
                            self._got_speech = True
                            self._frames.append(chunk)
                        elif level >= vad:
                            self._speech_run += 1
                            if self._speech_run >= min_speech:
                                self._got_speech = True
                                self._frames.append(chunk)
                        else:
                            self._speech_run = 0
                    else:
                        self._frames.append(chunk)
                        if level < vad:
                            self._silence_run += 1
                            if self._silence_run >= silence_end:
                                self._finish_listen()
                        else:
                            self._silence_run = 0
                        if len(self._frames) >= max_chunks:
                            self._finish_listen()

                if self._speaking and level >= barge:
                    self._barge_run += 1
                    if self._barge_run >= barge_trigger:
                        self._interrupt_playback()
                elif self._speaking:
                    self._barge_run = max(0, self._barge_run - 1)

    def capture_to(
        self,
        path: Path,
        *,
        assume_speaking: bool = False,
        listen_timeout_sec: int | None = None,
    ) -> bool:
        timeout = listen_timeout_sec if listen_timeout_sec is not None else int(
            os.getenv("LISTEN_TIMEOUT_SEC", "0")
        )
        deadline = time.time() + timeout if timeout > 0 else None

        with self._cond:
            self._listening = True
            self._listen_done = False
            self._assume_speaking = assume_speaking
            self._got_speech = assume_speaking
            self._frames = []
            self._speech_run = 0
            self._silence_run = 0

        while True:
            with self._cond:
                if self._listen_done:
                    break
                if deadline and time.time() >= deadline and not self._got_speech:
                    self._listening = False
                    self._listen_done = True
                    break
            with self._cond:
                self._cond.wait(timeout=0.15)

        with self._lock:
            if not self._frames:
                return False
            _write_pcm_wav(path, b"".join(self._frames))
            return True

    def wait_listen_to(self, path: Path) -> bool:
        with self._cond:
            while self._listening:
                self._cond.wait(timeout=0.15)
        with self._lock:
            if not self._frames:
                return False
            _write_pcm_wav(path, b"".join(self._frames))
            return True

    def play_interruptible(self, audio_path: Path) -> bool:
        suffix = audio_path.suffix.lower()
        wav = audio_path
        temp_wav: Path | None = None
        if suffix != ".wav":
            temp_wav = audio_path.with_suffix(".duplex.play.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path), str(temp_wav)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wav = temp_wav

        with self._cond:
            self._interrupted = False
            self._speaking = True
            self._barge_run = 0

        self._player = start_playback(wav)
        time.sleep(0.08)
        if self._player.poll() is not None:
            err = (self._player.stderr.read() or b"").decode(errors="replace").strip()
            with self._cond:
                self._speaking = False
            if temp_wav and temp_wav.exists():
                temp_wav.unlink(missing_ok=True)
            raise RuntimeError(
                f"播放失败（后端 {os.getenv('PLAYBACK_BACKEND', 'aplay')}）: "
                f"{err or 'unknown'}"
            )

        try:
            while True:
                with self._cond:
                    if self._interrupted:
                        return True
                    if self._player.poll() is not None:
                        self._speaking = False
                        return False
                time.sleep(0.04)
        finally:
            if self._player and self._player.poll() is None:
                self._player.kill()
            self._player = None
            if temp_wav and temp_wav.exists():
                temp_wav.unlink(missing_ok=True)


_duplex: DuplexMicrophone | None = None


def get_duplex() -> DuplexMicrophone:
    global _duplex
    if _duplex is None:
        _duplex = DuplexMicrophone()
    return _duplex


def shutdown_duplex() -> None:
    global _duplex
    if _duplex is not None:
        _duplex.stop()
        _duplex = None
