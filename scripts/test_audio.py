#!/usr/bin/env python3
"""检测树莓派麦克风/扬声器并试听。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from voice_io import (
    audio_setup_hint,
    describe_audio_hardware,
    discover_capture_device,
    discover_playback_device,
    find_working_playback,
    is_speaker_available,
    resolve_audio_devices,
    _make_probe_wav,
    _playback_probe_order,
    _probe_aplay,
)


def _test_microphone(mic: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "mic_test.wav"
        try:
            subprocess.run(
                [
                    "arecord",
                    "-q",
                    "-D",
                    mic,
                    "-d",
                    "2",
                    "-f",
                    "S16_LE",
                    "-r",
                    "16000",
                    "-c",
                    "1",
                    str(wav),
                ],
                check=True,
                timeout=10,
            )
            return wav.exists() and wav.stat().st_size > 1000
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return False


def main() -> None:
    print("=== 音频设备检测 ===\n")
    subprocess.run(["arecord", "-l"], check=False)
    print()
    subprocess.run(["aplay", "-l"], check=False)
    print()

    auto_mic = discover_capture_device()
    auto_spk = discover_playback_device()
    print(f"自动检测麦克风: {auto_mic or '未找到'}")
    print(f"自动检测扬声器: {auto_spk or '未找到'}")
    print()

    mic, spk = resolve_audio_devices()
    print(describe_audio_hardware())
    print()

    print("麦克风录音 2 秒…")
    if _test_microphone(mic):
        print("麦克风: OK")
    else:
        print(f"麦克风: 失败（设备 {mic}）")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "probe.wav"
        _make_probe_wav(probe)

        print("逐个探测扬声器…")
        working = ""
        for device in _playback_probe_order(spk):
            ok = _probe_aplay(device, probe)
            mark = "OK" if ok else "fail"
            print(f"  [{mark}] {device}")
            if ok and not working:
                working = device

        if not working:
            device, backend = find_working_playback(probe, preferred=spk)
            if device:
                working = f"{device} ({backend})"

        if not is_speaker_available():
            print()
            print("扬声器: 全部失败（当前树莓派听不到声音）")
            print(audio_setup_hint())
            sys.exit(2)

        print(f"\n扬声器: OK → 使用 {working or spk}")

        mp3 = Path(td) / "test.mp3"
        try:
            import asyncio

            from companion_brain import CompanionBrain
            from voice_io import text_to_speech_file

            brain = CompanionBrain()
            tts = brain.tts_config()
            print(f"合成测试（{tts.backend} / {tts.voice}）…")
            asyncio.run(
                text_to_speech_file(
                    "嗯，我在。这是一段路遥男声测试。", mp3, tts
                )
            )
            from audio_duplex import get_duplex, shutdown_duplex

            duplex = get_duplex()
            duplex.start()
            print("播放测试（可开口打断）…")
            interrupted = duplex.play_interruptible(mp3)
            shutdown_duplex()
            if interrupted:
                print("检测到打断。")
            else:
                print("播放完成。")
        except Exception as e:
            print(f"试听失败: {e}")
            sys.exit(1)

    print("\n完成。可将 MIC/SPK 写入 src/.env 固定设备。")


if __name__ == "__main__":
    main()
